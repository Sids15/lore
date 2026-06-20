//! Sidecar process supervision.
//!
//! The Python FastAPI backend ("sidecar") runs as a child process of the Tauri
//! shell. This module starts it when the app launches and terminates it when the
//! app exits, so the user never has to manage the backend manually.
//!
//! In development the sidecar is launched with the project's virtual-environment
//! Python (falling back to `python` on PATH). Production packaging will instead
//! ship a PyInstaller binary; that seam is added in the packaging phase.

use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::sync::Mutex;

use tauri::{AppHandle, Manager};

/// Default loopback host the sidecar binds to (overridable via `LORE_HOST`).
const DEFAULT_HOST: &str = "127.0.0.1";
/// Default port the sidecar binds to (overridable via `LORE_PORT`).
const DEFAULT_PORT: &str = "8765";

/// Managed Tauri state holding the running sidecar child process.
#[derive(Default)]
pub struct SidecarProcess(pub Mutex<Option<Child>>);

/// Directory containing the Python sidecar, resolved relative to this crate.
fn sidecar_dir() -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("sidecar")
}

/// Pick the Python interpreter: prefer the project venv, else fall back to PATH.
fn python_executable(sidecar_dir: &Path) -> PathBuf {
    #[cfg(windows)]
    let venv = sidecar_dir.join(".venv").join("Scripts").join("python.exe");
    #[cfg(not(windows))]
    let venv = sidecar_dir.join(".venv").join("bin").join("python");

    if venv.exists() {
        venv
    } else {
        PathBuf::from(if cfg!(windows) { "python" } else { "python3" })
    }
}

/// Build the uvicorn command that runs the sidecar.
fn build_command() -> Command {
    let dir = sidecar_dir();
    let python = python_executable(&dir);

    let host = std::env::var("LORE_HOST").unwrap_or_else(|_| DEFAULT_HOST.to_string());
    let port = std::env::var("LORE_PORT").unwrap_or_else(|_| DEFAULT_PORT.to_string());

    let mut cmd = Command::new(python);
    cmd.current_dir(&dir).args([
        "-m",
        "uvicorn",
        "app.main:app",
        "--host",
        &host,
        "--port",
        &port,
    ]);

    // Enable the sidecar's parent-watchdog and give it a piped stdin to watch.
    // The Child (held in managed state) keeps the write end open; if this shell
    // dies for any reason the pipe closes, the sidecar sees EOF and exits, so it
    // never orphans the port.
    cmd.env("LORE_PARENT_WATCHDOG", "1").stdin(Stdio::piped());

    // Suppress the extra console window that would otherwise appear on Windows.
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        cmd.creation_flags(CREATE_NO_WINDOW);
    }

    cmd
}

/// Start the sidecar and store the handle in managed state.
pub fn spawn(app: &AppHandle) -> std::io::Result<()> {
    let child = build_command().spawn()?;
    if let Some(state) = app.try_state::<SidecarProcess>() {
        *state.0.lock().expect("sidecar mutex poisoned") = Some(child);
    }
    Ok(())
}

/// Terminate the sidecar if it is still running. Safe to call multiple times.
pub fn shutdown(app: &AppHandle) {
    if let Some(state) = app.try_state::<SidecarProcess>() {
        if let Ok(mut guard) = state.0.lock() {
            if let Some(mut child) = guard.take() {
                let _ = child.kill();
                let _ = child.wait();
            }
        }
    }
}
