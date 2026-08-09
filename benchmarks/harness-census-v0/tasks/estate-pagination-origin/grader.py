#!/usr/bin/env python3
"""Offline behavioral grader for pagination origin validation."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile


CHECKS = ("relative-path", "scheme-check", "host-check", "port-check", "pagination-use", "request-path")


def fail(check: str, detail: str, passed_checks: int = 0) -> None:
    total_checks = len(CHECKS)
    print(json.dumps({"passed": False, "hard_pass": False, "passed_checks": passed_checks, "total_checks": total_checks, "task_points": passed_checks / total_checks, "failed_check": check, "detail": detail}, sort_keys=True))
    raise SystemExit(1)


ORACLE = r'''
#[cfg(test)]
mod harness_census_pagination_oracle {
    use std::io::{Read, Write};
    use std::net::TcpListener;
    use std::sync::{
        atomic::{AtomicUsize, Ordering},
        Arc,
    };
    use std::thread;
    use std::time::{Duration, Instant};

    fn serve_json(
        listener: TcpListener,
        bodies: Vec<String>,
        hits: Arc<AtomicUsize>,
    ) -> thread::JoinHandle<()> {
        thread::spawn(move || {
            listener.set_nonblocking(true).unwrap();
            let deadline = Instant::now() + Duration::from_secs(2);
            for body in bodies {
                'request: loop {
                    match listener.accept() {
                        Ok((mut stream, _)) => {
                            hits.fetch_add(1, Ordering::SeqCst);
                            let mut request = [0_u8; 4096];
                            let _ = stream.read(&mut request);
                            let response = format!(
                                "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: {}\r\nConnection: close\r\n\r\n{}",
                                body.len(),
                                body
                            );
                            let _ = stream.write_all(response.as_bytes());
                            break 'request;
                        }
                        Err(error) if error.kind() == std::io::ErrorKind::WouldBlock => {
                            if Instant::now() >= deadline {
                                break 'request;
                            }
                            thread::sleep(Duration::from_millis(10));
                        }
                        Err(error) => panic!("pagination oracle listener failed: {error}"),
                    }
                }
            }
        })
    }

    fn app_page(next: Option<&str>) -> String {
        match next {
            Some(next) => format!(
                r#"{{"apps":[],"links":{{"pages":{{"next":"{next}"}}}}}}"#
            ),
            None => r#"{"apps":[],"links":{"pages":{}}}"#.into(),
        }
    }

    fn droplet_page(next: Option<&str>) -> String {
        match next {
            Some(next) => format!(
                r#"{{"droplets":[],"links":{{"pages":{{"next":"{next}"}}}}}}"#
            ),
            None => r#"{"droplets":[],"links":{"pages":{}}}"#.into(),
        }
    }

    async fn run_apps(
        base: TcpListener,
        bodies: Vec<String>,
        attacker: Option<TcpListener>,
    ) -> (bool, usize, usize) {
        let base_hits = Arc::new(AtomicUsize::new(0));
        let attacker_hits = Arc::new(AtomicUsize::new(0));
        let base_url = base_url(base.try_clone().unwrap());
        let base_thread = serve_json(base, bodies, base_hits.clone());
        let attacker_thread = attacker.map(|listener| serve_json(listener, vec![app_page(None)], attacker_hits.clone()));
        let result = super::fetch_apps(&reqwest::Client::new(), &base_url, "token").await;
        base_thread.join().unwrap();
        if let Some(thread) = attacker_thread {
            thread.join().unwrap();
        }
        (
            result.is_ok(),
            base_hits.load(Ordering::SeqCst),
            attacker_hits.load(Ordering::SeqCst),
        )
    }

    fn base_url(listener: TcpListener) -> String {
        format!("http://{}", listener.local_addr().unwrap())
    }

    async fn run_droplets(
        base: TcpListener,
        bodies: Vec<String>,
        attacker: Option<TcpListener>,
    ) -> (bool, usize, usize) {
        let base_hits = Arc::new(AtomicUsize::new(0));
        let attacker_hits = Arc::new(AtomicUsize::new(0));
        let base_url = base_url(base.try_clone().unwrap());
        let base_thread = serve_json(base, bodies, base_hits.clone());
        let attacker_thread = attacker.map(|listener| serve_json(listener, vec![droplet_page(None)], attacker_hits.clone()));
        let result = super::fetch_droplets(&reqwest::Client::new(), &base_url, "token").await;
        base_thread.join().unwrap();
        if let Some(thread) = attacker_thread {
            thread.join().unwrap();
        }
        (
            result.is_ok(),
            base_hits.load(Ordering::SeqCst),
            attacker_hits.load(Ordering::SeqCst),
        )
    }

    #[tokio::test]
    async fn accepts_relative_and_exact_origin_pagination() {
        let base = TcpListener::bind("127.0.0.1:0").unwrap();
        let (ok, base_hits, attacker_hits) = run_apps(
            base,
            vec![app_page(Some("/v2/apps?page=2")), app_page(None)],
            None,
        )
        .await;
        assert!(ok, "relative-path: relative pagination failed");
        assert_eq!(base_hits, 2, "relative-path: second page was not requested");
        assert_eq!(attacker_hits, 0);

        let base = TcpListener::bind("127.0.0.1:0").unwrap();
        let url = base_url(base.try_clone().unwrap());
        let (ok, base_hits, attacker_hits) = run_apps(
            base,
            vec![app_page(Some(&format!("{url}/v2/apps?page=2"))), app_page(None)],
            None,
        )
        .await;
        assert!(ok, "request-path: exact-origin pagination failed");
        assert_eq!(base_hits, 2, "request-path: exact-origin page was not requested");
        assert_eq!(attacker_hits, 0);
    }

    #[tokio::test]
    async fn rejects_cross_origin_host_before_request() {
        let base = TcpListener::bind("127.0.0.1:0").unwrap();
        let attacker = TcpListener::bind("127.0.0.1:0").unwrap();
        let hostile = format!("http://localhost:{}/steal", attacker.local_addr().unwrap().port());
        let (ok, base_hits, attacker_hits) = run_apps(
            base,
            vec![app_page(Some(&hostile))],
            Some(attacker),
        )
        .await;
        assert_eq!(base_hits, 1, "host-check: base page was not requested");
        assert!(!ok, "host-check: accepted a cross-origin pagination link");
        assert_eq!(attacker_hits, 0, "host-check: attacker request was issued");
    }

    #[tokio::test]
    async fn rejects_scheme_mismatch_before_request() {
        let base = TcpListener::bind("127.0.0.1:0").unwrap();
        let url = base_url(base.try_clone().unwrap());
        let hostile = url.replacen("http://", "https://", 1) + "/v2/apps?page=2";
        let (ok, base_hits, attacker_hits) = run_apps(
            base,
            vec![app_page(Some(&hostile)), app_page(None)],
            None,
        )
        .await;
        assert_eq!(base_hits, 1, "scheme-check: mismatched scheme was requested");
        assert!(!ok, "scheme-check: accepted a mismatched scheme");
        assert_eq!(attacker_hits, 0);
    }

    #[tokio::test]
    async fn rejects_effective_port_mismatch_before_request() {
        let base = TcpListener::bind("127.0.0.1:0").unwrap();
        let attacker = TcpListener::bind("127.0.0.1:0").unwrap();
        let hostile = format!("http://{}/steal", attacker.local_addr().unwrap());
        let (ok, base_hits, attacker_hits) = run_apps(
            base,
            vec![app_page(Some(&hostile))],
            Some(attacker),
        )
        .await;
        assert_eq!(base_hits, 1, "port-check: base page was not requested");
        assert!(!ok, "port-check: accepted a mismatched effective port");
        assert_eq!(attacker_hits, 0, "port-check: mismatched port was requested");
    }

    #[tokio::test]
    async fn rejects_schema_relative_links_before_request() {
        let base = TcpListener::bind("127.0.0.1:0").unwrap();
        let (ok, base_hits, attacker_hits) = run_apps(
            base,
            vec![app_page(Some("//attacker.invalid/steal")), app_page(None)],
            None,
        )
        .await;
        assert_eq!(base_hits, 1, "scheme-check: schema-relative link was requested");
        assert!(!ok, "scheme-check: accepted a schema-relative link");
        assert_eq!(attacker_hits, 0);
    }

    #[tokio::test]
    async fn validates_every_apps_pagination_link() {
        let base = TcpListener::bind("127.0.0.1:0").unwrap();
        let attacker = TcpListener::bind("127.0.0.1:0").unwrap();
        let hostile = format!("http://{}/steal", attacker.local_addr().unwrap());
        let (ok, base_hits, attacker_hits) = run_apps(
            base,
            vec![app_page(Some("/v2/apps?page=2")), app_page(Some(&hostile))],
            Some(attacker),
        )
        .await;
        assert_eq!(base_hits, 2, "pagination-use: first next page was not requested");
        assert!(!ok, "pagination-use: accepted a later cross-origin link");
        assert_eq!(attacker_hits, 0, "pagination-use: later link reached attacker");
    }

    #[tokio::test]
    async fn validates_droplet_pagination_links() {
        let base = TcpListener::bind("127.0.0.1:0").unwrap();
        let attacker = TcpListener::bind("127.0.0.1:0").unwrap();
        let hostile = format!("http://{}/steal", attacker.local_addr().unwrap());
        let (ok, base_hits, attacker_hits) = run_droplets(
            base,
            vec![droplet_page(Some(&hostile))],
            Some(attacker),
        )
        .await;
        assert_eq!(base_hits, 1, "pagination-use: droplet page was not requested");
        assert!(!ok, "pagination-use: accepted a droplet cross-origin link");
        assert_eq!(attacker_hits, 0, "pagination-use: droplet link reached attacker");
    }
}
'''

def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: grader.py REPOSITORY")
    repo = Path(sys.argv[1]).resolve()
    source = repo / "src" / "collect" / "digitalocean.rs"
    if not source.is_file() or not (repo / "Cargo.toml").is_file():
        fail("invalid-syntax", "target Rust source or Cargo manifest is missing")
    try:
        source.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        fail("invalid-syntax", str(error))
    original = source.read_bytes()
    try:
        source.write_bytes(original + ORACLE.encode("utf-8"))
        env = os.environ.copy()
        env.update({"CARGO_NET_OFFLINE": "true", "CARGO_TERM_COLOR": "never"})
        with tempfile.TemporaryDirectory(prefix="harness-census-cargo-") as target:
            env["CARGO_TARGET_DIR"] = target
            result = subprocess.run(
                ["cargo", "test", "--offline", "harness_census_pagination_oracle", "--", "--nocapture"],
                cwd=repo,
                env=env,
                text=True,
                capture_output=True,
                timeout=45,
                check=False,
            )
    except subprocess.TimeoutExpired as error:
        fail("setup-timeout", f"offline Rust probe exceeded its deterministic timeout: {error}")
    except (OSError, subprocess.SubprocessError) as error:
        fail("invalid-syntax", str(error))
    finally:
        source.write_bytes(original)
    if result.returncode:
        output = (result.stdout + result.stderr)[-5000:]
        for marker in ("relative-path", "request-path", "host-check", "scheme-check", "port-check", "pagination-use"):
            if marker in output:
                fail(marker, output, len(CHECKS) - 1)
        if "could not find" in output or "cannot find function" in output:
            fail("invalid-syntax", output)
        fail("invalid-syntax", output)
    total_checks = len(CHECKS)
    print(json.dumps({"passed": True, "hard_pass": True, "passed_checks": total_checks, "total_checks": total_checks, "task_points": 1.0, "checks": list(CHECKS)}, sort_keys=True))


if __name__ == "__main__":
    main()
