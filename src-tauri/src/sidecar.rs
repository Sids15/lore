//! Sidecar process supervision.
//!
//! The Python FastAPI backend ("sidecar") runs as a child process of the Tauri
//! shell. This module starts it when the app launches and terminates it when the
//! app exits, so the user never has to manage the backend manually.
//!
//! Two launch paths:
//! * **Packaged** — run the bundled PyInstaller binary shipped as a resource
//!   (`lore-sidecar/lore-sidecar(.exe)`), with data stored under the per-user
//!   app-data directory (resources are read-only).
//! * **Development** — fall back to the project virtualenv: `python -m uvicorn`.

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

/// Locate the bundled PyInstaller sidecar binary among the app's resources.
///
/// Returns `None` in development (the binary is only shipped in packaged builds),
/// so the caller falls back to running uvicorn from the venv.
fn bundled_sidecar(app: &AppHandle) -> Option<PathBuf> {
    let resource_dir = app.path().resource_dir().ok()?;
    let exe = if cfg!(windows) { "lore-sidecar.exe" } else { "lore-sidecar" };
    // Tauri may place the bundled folder either flat or nested by basename;
    // check both plausible layouts.
    let candidates = [
        resource_dir.join("lore-sidecar").join(exe),
        resource_dir
            .join("lore-sidecar")
            .join("lore-sidecar")
            .join(exe),
    ];
    candidates.into_iter().find(|path| path.exists())
}

/// Build the command that runs the sidecar (packaged binary, else dev uvicorn).
fn build_command(app: &AppHandle) -> Command {
    let host = std::env::var("LORE_HOST").unwrap_or_else(|_| DEFAULT_HOST.to_string());
    let port = std::env::var("LORE_PORT").unwrap_or_else(|_| DEFAULT_PORT.to_string());

    let mut cmd = match bundled_sidecar(app) {
        Some(binary) => {
            // Packaged: run the frozen binary; it reads LORE_HOST/PORT from env.
            let mut cmd = Command::new(&binary);
            if let Some(parent) = binary.parent() {
                cmd.current_dir(parent);
            }
            // Resources are read-only, so store the indexes/models in a writable
            // per-user directory instead of next to the binary.
            if let Ok(data_dir) = app.path().app_data_dir() {
                cmd.env("LORE_DATA_DIR", data_dir.join("data"));
            }
            cmd
        }
        None => {
            // Development: run uvicorn from the project virtualenv.
            let dir = sidecar_dir();
            let mut cmd = Command::new(python_executable(&dir));
            cmd.current_dir(&dir).args([
                "-m",
                "uvicorn",
                "app.main:app",
                "--host",
                &host,
                "--port",
                &port,
            ]);
            cmd
        }
    };

    // Enable the sidecar's parent-watchdog and give it a piped stdin to watch.
    // The Child (held in managed state) keeps the write end open; if this shell
    // dies for any reason the pipe closes, the sidecar sees EOF and exits, so it
    // never orphans the port.
    cmd.env("LORE_HOST", &host)
        .env("LORE_PORT", &port)
        .env("LORE_PARENT_WATCHDOG", "1")
        .stdin(Stdio::piped());

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
    let child = build_command(app).spawn()?;
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
