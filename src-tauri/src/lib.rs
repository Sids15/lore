//! Lore desktop shell (Tauri).
//!
//! This crate is the thin native host for the Lore application. Its job is to
//! create the application window that renders the React frontend. In later
//! phases it will also launch and supervise the Python "sidecar" process that
//! performs the RAG/ML work (see `sidecar.rs`).

/// Builds and runs the Tauri application.
///
/// `mobile_entry_point` lets the same entry point work on desktop and mobile
/// targets; on desktop it is invoked from `main.rs`.
#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .run(tauri::generate_context!())
        .expect("error while running Lore");
}
