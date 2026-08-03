use std::{
  io::{Read, Write},
  net::{Ipv4Addr, SocketAddr, TcpListener, TcpStream},
  process::Command,
  sync::Mutex,
  thread,
  time::Duration,
};

use tauri::{Manager, RunEvent};
use tauri_plugin_shell::{process::CommandChild, ShellExt};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

const CREATE_NO_WINDOW: u32 = 0x08000000;

struct ApiPort(u16);

struct BackendProcess {
  child: Mutex<Option<CommandChild>>,
  pid: u32,
}

#[tauri::command]
fn api_base_url(port: tauri::State<'_, ApiPort>) -> String {
  format!("http://127.0.0.1:{}", port.0)
}

fn reserve_loopback_port() -> std::io::Result<u16> {
  let listener = TcpListener::bind((Ipv4Addr::LOCALHOST, 0))?;
  Ok(listener.local_addr()?.port())
}

fn backend_is_healthy(port: u16) -> bool {
  let address = SocketAddr::from((Ipv4Addr::LOCALHOST, port));
  let Ok(mut stream) = TcpStream::connect_timeout(&address, Duration::from_secs(1)) else {
    return false;
  };

  let _ = stream.set_read_timeout(Some(Duration::from_secs(2)));
  let _ = stream.set_write_timeout(Some(Duration::from_secs(2)));
  let request = format!(
    "GET /api/health HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nConnection: close\r\n\r\n"
  );
  if stream.write_all(request.as_bytes()).is_err() {
    return false;
  }

  let mut response = String::new();
  stream.read_to_string(&mut response).is_ok()
    && response.contains(" 200 ")
    && response.contains("\"status\":\"ok\"")
}

fn wait_for_backend(port: u16) -> bool {
  (0..240).any(|_| {
    if backend_is_healthy(port) {
      true
    } else {
      thread::sleep(Duration::from_millis(500));
      false
    }
  })
}

fn stop_backend(app: &tauri::AppHandle) {
  let Some(state) = app.try_state::<BackendProcess>() else {
    return;
  };
  let Ok(mut child_guard) = state.child.lock() else {
    return;
  };
  let Some(child) = child_guard.take() else {
    return;
  };

  #[cfg(windows)]
  {
    let _ = Command::new("taskkill")
      .args(["/PID", &state.pid.to_string(), "/T", "/F"])
      .creation_flags(CREATE_NO_WINDOW)
      .status();
  }

  let _ = child.kill();
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
  let app = tauri::Builder::default()
    .plugin(tauri_plugin_shell::init())
    .invoke_handler(tauri::generate_handler![api_base_url])
    .setup(|app| {
      let port = reserve_loopback_port()?;
      let port_argument = port.to_string();
      let (mut events, child) = app
        .shell()
        .sidecar("desktop-backend")?
        .args(["--port", port_argument.as_str()])
        .spawn()?;
      let pid = child.pid();

      app.manage(ApiPort(port));
      app.manage(BackendProcess {
        child: Mutex::new(Some(child)),
        pid,
      });

      tauri::async_runtime::spawn(async move {
        while events.recv().await.is_some() {}
      });

      let app_handle = app.handle().clone();
      thread::spawn(move || {
        let ready = wait_for_backend(port);
        if let Some(window) = app_handle.get_webview_window("main") {
          if !ready {
            let _ = window.eval(
              "document.body.innerHTML='<main style=\"font-family:Microsoft YaHei,sans-serif;padding:48px;color:#173239\"><h1>教学辅助服务启动失败</h1><p>请关闭应用后重新启动。</p></main>'",
            );
          }
          let _ = window.show();
          let _ = window.set_focus();
        }
      });

      Ok(())
    })
    .build(tauri::generate_context!())
    .expect("failed to build desktop application");

  app.run(|app_handle, event| {
    if matches!(event, RunEvent::ExitRequested { .. } | RunEvent::Exit) {
      stop_backend(app_handle);
    }
  });
}
