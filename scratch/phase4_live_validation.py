import sys
import time
import json
import httpx
from pathlib import Path

# Add backend to sys.path
backend_dir = Path(r"c:\Users\saipr\OneDrive\Documents\ml_project\crime-analysis\backend")
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.config import settings
from app.database import SessionLocal
from app.models import Case, Person, Entity, Evidence, Relationship, Event, Document, User
from app.services.graph_sync import sync_case_to_neo4j
from app.services.graph_view import get_case_graph
from app.services.neo4j_service import run_read_query
from app.services.graph_analysis import analyze_cases
from app.services.nvidia_client import stream_chat

BASE_URL = "http://localhost:8000"

def run_validation():
    print("=== STARTING PHASE 4 LIVE VALIDATION ===")
    results = {}
    
    # 1. Health check & 30s cache test
    t0 = time.perf_counter()
    r1 = httpx.get(f"{BASE_URL}/health", timeout=30.0)
    t1 = time.perf_counter()
    r2 = httpx.get(f"{BASE_URL}/health", timeout=30.0)
    t2 = time.perf_counter()
    
    health_first_ms = (t1 - t0) * 1000
    health_cached_ms = (t2 - t1) * 1000
    print(f"[HEALTH] First call: {health_first_ms:.2f}ms, Cached call: {health_cached_ms:.2f}ms")
    results["health_cached_ms"] = health_cached_ms
    
    # 2. Authentication & Security
    s = httpx.Client(timeout=30.0)
    login_resp = s.post(f"{BASE_URL}/api/auth/login", json={"username": "investigator1", "password": "investor1"})
    assert login_resp.status_code == 200, f"Login failed: {login_resp.text}"
    cookie = s.cookies.get("crime_analysis_session")
    assert cookie is not None, "HttpOnly session cookie missing!"
    print(f"[AUTH] Logged in successfully. Cookie set: crime_analysis_session exists (length={len(cookie)})")
    
    # Verify RBAC: investigator cannot access /api/admin/users
    admin_access = s.get(f"{BASE_URL}/api/admin/users")
    assert admin_access.status_code == 403, f"Expected 403 for investigator on admin route, got {admin_access.status_code}"
    print("[AUTH] RBAC verified: investigator correctly blocked with 403 from admin routes.")
    
    # 3. Case Consistency Validation for C101, C204, C-3A3FE7
    cases_to_check = ["C101", "C204", "C-3A3FE7"]
    consistency_results = {}
    db = SessionLocal()
    
    admin_user = db.query(User).filter_by(username="admin").first()
    
    for cid in cases_to_check:
        print(f"\n--- Checking Case {cid} ---")
        t_sync_0 = time.perf_counter()
        sync_res = sync_case_to_neo4j(db, cid)
        t_sync = (time.perf_counter() - t_sync_0) * 1000
        
        # Second sync to verify idempotency
        sync_res_2 = sync_case_to_neo4j(db, cid)
        
        verification = sync_res.get("verification", {})
        matched = verification.get("matched", False)
        sql_counts = verification.get("sql", {})
        neo4j_counts = verification.get("neo4j", {})
        mismatches = verification.get("mismatches", [])
        
        # Cytoscape view query
        graph_view_res = get_case_graph(db, admin_user, [cid])
        cyto_nodes = len(graph_view_res["nodes"])
        cyto_edges = len(graph_view_res["edges"])
        
        print(f"Case {cid}: Sync time = {t_sync:.2f}ms")
        print(f"SQL counts: {sql_counts}")
        print(f"Neo4j counts: {neo4j_counts}")
        print(f"Consistency Matched: {matched} (Mismatches: {mismatches})")
        print(f"Cytoscape view received: {cyto_nodes} nodes, {cyto_edges} edges, source: {graph_view_res['source']}")
        
        consistency_results[cid] = {
            "sql_counts": sql_counts,
            "neo4j_counts": neo4j_counts,
            "matched": matched,
            "mismatches": mismatches,
            "sync_time_ms": t_sync,
            "cyto_nodes": cyto_nodes,
            "cyto_edges": cyto_edges,
            "idempotent": verification == sync_res_2.get("verification")
        }
    
    # 4. Decoupled Graph Analysis Performance
    print("\n--- Measuring Graph Analysis Performance ---")
    t_ga_0 = time.perf_counter()
    ga_res = analyze_cases(db, admin_user, ["C101"])
    t_ga = (time.perf_counter() - t_ga_0) * 1000
    print(f"Graph Analysis: time = {t_ga:.2f}ms, nodes = {ga_res['entity_count']}, edges = {ga_res['edge_count']}, engine = {ga_res['engine']}")
    results["graph_analysis_time_ms"] = t_ga
    
    # 5. NVIDIA Streaming Performance (Primary & Fallback)
    print("\n--- Measuring NVIDIA AI Performance ---")
    messages = [
        {"role": "user", "content": "Provide a 1-sentence summary of investigative priorities."}
    ]
    
    # Test Primary Model
    print(f"Testing Primary Model: {settings.NVIDIA_MODEL}")
    t_ai_start = time.perf_counter()
    ttft = None
    first_token_time = None
    chunks = []
    try:
        for chunk in stream_chat(messages):
            if ttft is None:
                first_token_time = time.perf_counter()
                ttft = (first_token_time - t_ai_start) * 1000
            chunks.append(chunk)
        t_ai_end = time.perf_counter()
        total_ai_time = (t_ai_end - t_ai_start) * 1000
        print(f"Primary Model Success: TTFT = {ttft:.2f}ms, Total AI Time = {total_ai_time:.2f}ms, Chunks = {len(chunks)}")
        results["primary_ttft_ms"] = ttft
        results["primary_total_ms"] = total_ai_time
    except Exception as e:
        print(f"Primary Model Exception: {e}")
        results["primary_error"] = str(e)
        
    # Test Fallback Model directly
    print(f"\nTesting Fallback Model: {settings.NVIDIA_FALLBACK_MODEL}")
    old_primary = settings.NVIDIA_MODEL
    try:
        settings.NVIDIA_MODEL = settings.NVIDIA_FALLBACK_MODEL
        t_fb_start = time.perf_counter()
        fb_ttft = None
        fb_chunks = []
        for chunk in stream_chat(messages):
            if fb_ttft is None:
                fb_first_token = time.perf_counter()
                fb_ttft = (fb_first_token - t_fb_start) * 1000
            fb_chunks.append(chunk)
        t_fb_end = time.perf_counter()
        total_fb_time = (t_fb_end - t_fb_start) * 1000
        print(f"Fallback Model Success: TTFT = {fb_ttft:.2f}ms, Total AI Time = {total_fb_time:.2f}ms, Chunks = {len(fb_chunks)}")
        results["fallback_ttft_ms"] = fb_ttft
        results["fallback_total_ms"] = total_fb_time
    except Exception as e:
        print(f"Fallback Model Exception: {e}")
        results["fallback_error"] = str(e)
    finally:
        settings.NVIDIA_MODEL = old_primary
        
    db.close()
    
    # Save results to json
    results["consistency"] = consistency_results
    out_path = Path(__file__).resolve().parent / "phase4_validation_results.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nValidation complete! Results saved to {out_path}")

if __name__ == "__main__":
    run_validation()
