//! Lore desktop shell (Tauri).
//!
//! This crate is the native host for the Lore application. It creates the
//! application window that renders the React frontend and launches/supervises
//! the Python "sidecar" process that performs the RAG/ML work.

mod sidecar;

use sidecar::SidecarProcess;
use tauri::RunEvent;

/// Builds and runs the Tauri application.
///
/// `mobile_entry_point` lets the same entry point work on desktop and mobile
/// targets; on desktop it is invoked from `main.rs`.
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(SidecarProcess::default())
        .setup(|app| {
            // Start the backend as soon as the app is ready. A failure here is
            // logged but non-fatal: the UI surfaces the disconnected state.
            if let Err(error) = sidecar::spawn(&app.handle()) {
                eprintln!("Lore: failed to start sidecar: {error}");
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building Lore")
        .run(|app_handle, event| {
            // Ensure the sidecar is stopped when the app exits.
            if let RunEvent::Exit = event {
                sidecar::shutdown(app_handle);
            }
        });
}
