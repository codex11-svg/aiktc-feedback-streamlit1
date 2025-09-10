import streamlit as st
import requests
import base64
import json
import csv
import io
from datetime import datetime, timedelta, timezone

# =============== App Config ===============
st.set_page_config(page_title="AIKTC Anonymous Feedback", page_icon="📝", layout="wide")
st.title("📝 AIKTC Anonymous Feedback System")
st.markdown("Submit feedback or queries anonymously. Your identity remains protected.")

# =============== Secrets ===============
GITHUB_TOKEN = st.secrets["github_token"]
REPO = st.secrets["repo"]                 # e.g., "owner/repo"
BRANCH = st.secrets.get("branch", "main")
ADMIN_PASSWORD = st.secrets["admin_password"]

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

# =============== Utilities ===============
def utc_now_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

def parse_utc(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)

def get_file_content(path):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}?ref={BRANCH}"
    r = requests.get(url, headers=HEADERS)
    if r.status_code == 200:
        content = r.json()
        sha = content["sha"]
        file_data = base64.b64decode(content["content"]).decode()
        return file_data, sha, r.headers
    elif r.status_code == 404:
        return "[]", None, r.headers
    else:
        st.error(f"Error fetching {path} from GitHub: {r.status_code}")
        st.stop()

def update_file_content(path, data_str, sha, message):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    encoded = base64.b64encode(data_str.encode()).decode()
    payload = {"message": message, "content": encoded, "branch": BRANCH}
    if sha:
        payload["sha"] = sha
    return requests.put(url, headers=HEADERS, json=payload)

def load_json_list(path):
    data_str, sha, headers = get_file_content(path)
    try:
        items = json.loads(data_str)
    except Exception:
        items = []
    for it in items:
        it.setdefault("replies", [])
        it.setdefault("labels", [])
        it.setdefault("priority", "Medium")
        it.setdefault("assigned_to", "")
        it.setdefault("admin_notes", "")
        it.setdefault("reactions", {"like": 0, "helpful": 0, "agree": 0})
        it.setdefault("deleted_at", None)
        it.setdefault("history", [])
        it.setdefault("created_at", utc_now_str())
        it.setdefault("updated_at", it.get("created_at"))
    return items, sha, headers

def optimistic_save(path, items, old_sha, message, id_key="id"):
    # First attempt
    r = update_file_content(path, json.dumps(items, indent=2), old_sha, message)
    if r.status_code in (200, 201):
        return True, r
    # Conflict -> merge and retry
    if r.status_code in (409, 422):
        latest_str, latest_sha, _ = get_file_content(path)
        try:
            latest = json.loads(latest_str)
        except Exception:
            latest = []
        by_id = {x.get(id_key): x for x in latest if x.get(id_key) is not None}
        for it in items:
            iid = it.get(id_key)
            if iid is None:
                continue
            if iid not in by_id:
                by_id[iid] = it
            else:
                a = by_id[iid]
                b = it
                ta = parse_utc(a.get("updated_at", a.get("created_at", utc_now_str())))
                tb = parse_utc(b.get("updated_at", b.get("created_at", utc_now_str())))
                merged = a if ta >= tb else b
                merged["replies"] = a.get("replies", []) + [rr for rr in b.get("replies", [])]
                ra, rb = a.get("reactions", {}), b.get("reactions", {})
                merged["reactions"] = {
                    "like": int(ra.get("like", 0)) + int(rb.get("like", 0)),
                    "helpful": int(ra.get("helpful", 0)) + int(rb.get("helpful", 0)),
                    "agree": int(ra.get("agree", 0)) + int(rb.get("agree", 0)),
                }
                by_id[iid] = merged
        merged_list = list(by_id.values())
        r2 = update_file_content(path, json.dumps(merged_list, indent=2), latest_sha, message + " (merge)")
        return (r2.status_code in (200, 201)), r2
    return False, r

def mask_pii(text):
    import re
    if not text: return text
    text = re.sub(r'\b[\w\.-]+@[\w\.-]+\.\w{2,}\b', '[email masked]', text)
    text = re.sub(r'\b(?:\+?\d{1,3}[-.\s]?)?(?:\d{3}[-.\s]?){2}\d{4}\b', '[phone masked]', text)
    return text

def throttle_ok(key, limit_seconds=30, max_hourly=5):
    now = datetime.now(timezone.utc)
    hist = st.session_state.get(key, [])
    hist = [t for t in hist if (now - t).total_seconds() <= 3600]
    st.session_state[key] = hist
    if hist and (now - hist[-1]).total_seconds() < limit_seconds:
        return False, int(limit_seconds - (now - hist[-1]).total_seconds())
    if len(hist) >= max_hourly:
        return False, int(3600 - (now - hist).total_seconds())
    hist.append(now)
    st.session_state[key] = hist
    return True, 0

def add_history(item, action, before=None, after=None, author="admin"):
    item.setdefault("history", []).append({
        "action": action, "author": author, "at": utc_now_str(),
        "before": before, "after": after
    })

def filter_items(items, keyword, fields, status=None):
    kw = (keyword or "").lower().strip()
    out = []
    for it in items:
        if status and it.get("status") != status:
            continue
        if not kw:
            out.append(it); continue
        hay = []
        for f in fields:
            v = it.get(f, "")
            if isinstance(v, str):
                hay.append(v.lower())
            elif isinstance(v, list):
                hay.extend([str(x).lower() for x in v])
        for rp in it.get("replies", []):
            hay.append(str(rp.get("message", "")).lower())
        if any(kw in h for h in hay):
            out.append(it)
    return out

def paginate_items(items, page, size):
    start, end = page * size, page * size + size
    return items[start:end], len(items) > end

def to_csv(data, fields):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields)
    w.writeheader()
    for row in data:
        rc = dict(row)
        rc["replies_count"] = len(rc.get("replies", []))
        w.writerow({k: rc.get(k, "") for k in fields})
    return buf.getvalue()

def ensure_session_defaults():
    defaults = {
        "logged_in": False, "login_error": False,
        "pub_fb_page": 0, "pub_tk_open_page": 0,
        "pub_tk_completed_page": 0, "pub_tk_all_page": 0,
        "feedback_search_pub": "", "ticket_search_pub": ""
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)

ensure_session_defaults()

# =============== Load data ===============
feedback_list, feedback_sha, fb_headers = load_json_list("feedback.json")
tickets_list, tickets_sha, tk_headers = load_json_list("tickets.json")

# =============== Sidebar: Admin Login ===============
st.sidebar.title("🔐 Admin")
if not st.session_state["logged_in"]:
    pwd = st.sidebar.text_input("Enter admin password:", type="password", key="adm_pwd")
    if st.sidebar.button("Login", key="adm_login_btn"):
        if pwd == ADMIN_PASSWORD:
            st.session_state["logged_in"] = True
            st.session_state["login_error"] = False
            st.rerun()
        else:
            st.session_state["login_error"] = True
    if st.session_state["login_error"]:
        st.sidebar.error("❌ Incorrect password. Try again.")
else:
    st.sidebar.success("✅ Logged in")
    if st.sidebar.button("Logout", key="adm_logout_btn"):
        st.session_state["logged_in"] = False
        st.rerun()

# =============== Query params (deep links) ===============
qp = st.query_params.to_dict()
deep_ticket_id = int(qp.get("t", 0)) if qp.get("t") else None
deep_feedback_id = int(qp.get("fb", 0)) if qp.get("fb") else None

def set_ticket_param(i):
    st.query_params.t = str(i)

def set_feedback_param(i):
    st.query_params.fb = str(i)

# =============== Tabs ===============
if st.session_state["logged_in"]:
    tab_public, tab_admin = st.tabs(["Public View", "Admin Panel"])
else:
    tab_public = st.container()

# =============== Public View ===============
with tab_public:
    # Feedback submit
    st.header("Anonymous Feedback")
    with st.form("pub_feedback_form"):
        fb_msg = st.text_area("Write your feedback (Markdown supported):", "", height=100, key="pub_fb_text")
        colf1, colf2 = st.columns([1,1])
        with colf1:
            st.caption("Preview:")
            st.markdown(fb_msg or "_Nothing yet_")
        with colf2:
            st.caption("Tips: Use **bold**, - bullets.")
        submit_fb = st.form_submit_button("Submit Feedback", use_container_width=True)
    if submit_fb:
        ok, wait = throttle_ok("pub_fb_throttle", limit_seconds=30, max_hourly=5)
        if not ok:
            st.error(f"Rate limit: wait {wait} seconds or try later.")
        elif fb_msg.strip():
            new_fb = {
                "id": (max([fb["id"] for fb in feedback_list]) + 1) if feedback_list else 1,
                "message": mask_pii(fb_msg.strip()),
                "created_at": utc_now_str(),
                "updated_at": utc_now_str(),
                "replies": [],
                "labels": [],
                "priority": "Medium",
                "assigned_to": "",
                "admin_notes": "",
                "reactions": {"like": 0, "helpful": 0, "agree": 0},
                "deleted_at": None,
                "history": []
            }
            feedback_list.append(new_fb)
            ok_save, _ = optimistic_save("feedback.json", feedback_list, feedback_sha, "Add feedback")
            if ok_save:
                st.success("✅ Feedback submitted!")
                set_feedback_param(new_fb["id"])
                st.rerun()
            else:
                st.error("❌ Failed to save feedback.")
        else:
            st.error("❌ Please enter some feedback.")

    # Feedback list (recent)
    st.subheader("Recent Feedback (24h)")
    st.text_input("Search feedback:", key="feedback_search_pub", placeholder="Type to search feedback...")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    public_feedback = [x for x in feedback_list if parse_utc(x["created_at"]) > cutoff]
    filtered_feedback = filter_items(public_feedback, st.session_state["feedback_search_pub"], ["message", "admin_notes", "labels"])
    page_items, has_more = paginate_items(sorted(filtered_feedback, key=lambda x: x["created_at"], reverse=True), st.session_state["pub_fb_page"], 5)

    if page_items:
        for fb in page_items:
            expanded = (deep_feedback_id == fb["id"])
            with st.expander(f"Feedback #{fb['id']} • {fb['created_at']} UTC", expanded=expanded):
                st.markdown(fb["message"])
                colx1, colx2, colx3, colx4 = st.columns([1,1,1,3])
                with colx1:
                    if st.button(f"👍 {fb['reactions'].get('like',0)}", key=f"pub_fb_like_btn_{fb['id']}"):
                        fb["reactions"]["like"] = fb["reactions"].get("like",0) + 1
                        fb["updated_at"] = utc_now_str()
                        optimistic_save("feedback.json", feedback_list, feedback_sha, "React feedback")
                        st.rerun()
                with colx2:
                    if st.button(f"✅ {fb['reactions'].get('helpful',0)}", key=f"pub_fb_helpful_btn_{fb['id']}"):
                        fb["reactions"]["helpful"] = fb["reactions"].get("helpful",0) + 1
                        fb["updated_at"] = utc_now_str()
                        optimistic_save("feedback.json", feedback_list, feedback_sha, "React feedback")
                        st.rerun()
                with colx3:
                    if st.button(f"🙌 {fb['reactions'].get('agree',0)}", key=f"pub_fb_agree_btn_{fb['id']}"):
                        fb["reactions"]["agree"] = fb["reactions"].get("agree",0) + 1
                        fb["updated_at"] = utc_now_str()
                        optimistic_save("feedback.json", feedback_list, feedback_sha, "React feedback")
                        st.rerun()
                with colx4:
                    if st.button("Copy link", key=f"pub_fb_link_btn_{fb['id']}"):
                        set_feedback_param(fb["id"])
                        st.success("Link set in URL")
                if fb.get("replies"):
                    st.markdown("**Admin Replies:**")
                    for reply in fb["replies"]:
                        st.markdown(f"- {reply['message']} (at {reply['created_at']} UTC)")
    else:
        st.write("No feedback available.")
    if has_more:
        if st.button("Load more feedback", key="pub_fb_load_more"):
            st.session_state["pub_fb_page"] += 1
            st.rerun()

    # Ticket submission
    st.header("Submit a Ticket/Query")
    with st.form("pub_ticket_form"):
        ticket_query = st.text_area("Write your query (Markdown supported):", "", height=100, key="pub_tk_text")
        colp1, colp2 = st.columns([1,1])
        with colp1:
            st.caption("Preview:")
            st.markdown(ticket_query or "_Nothing yet_")
        with colp2:
            priority_new = st.selectbox("Priority", ["Low","Medium","High"], index=1, key="pub_tk_priority")
        submit_ticket = st.form_submit_button("Submit Ticket", use_container_width=True)
    if submit_ticket:
        ok, wait = throttle_ok("pub_tk_throttle", limit_seconds=30, max_hourly=5)
        if not ok:
            st.error(f"Rate limit: wait {wait} seconds or try later.")
        elif ticket_query.strip():
            new_ticket = {
                "id": (max([t["id"] for t in tickets_list]) + 1) if tickets_list else 1,
                "query": mask_pii(ticket_query.strip()),
                "status": "In Process",
                "created_at": utc_now_str(),
                "updated_at": utc_now_str(),
                "replies": [],
                "labels": [],
                "priority": priority_new,
                "assigned_to": "",
                "admin_notes": "",
                "reactions": {"like": 0, "helpful": 0, "agree": 0},
                "deleted_at": None,
                "history": []
            }
            tickets_list.append(new_ticket)
            ok_save, _ = optimistic_save("tickets.json", tickets_list, tickets_sha, "Add ticket")
            if ok_save:
                st.success("✅ Ticket submitted!")
                set_ticket_param(new_ticket["id"])
                st.rerun()
            else:
                st.error("❌ Failed to save ticket.")
        else:
            st.error("❌ Please enter a query.")

    # Ticket views: Open / Completed / All
    st.header("View Tickets")
    t_open, t_completed, t_all = st.tabs(["Open", "Completed", "All"])
    st.text_input("Search tickets:", key="ticket_search_pub", placeholder="Type to search tickets...")

    def render_ticket_list(data, view_prefix):
        page_key = f"{view_prefix}_page"
        if page_key not in st.session_state:
            st.session_state[page_key] = 0
        page_items, has_more_local = paginate_items(data, st.session_state[page_key], 5)
        if page_items:
            for ticket in page_items:
                expanded = (deep_ticket_id == ticket["id"])
                chip = "✅ Completed" if ticket["status"] == "Completed" else "🟡 In Process"
                with st.expander(f"Ticket #{ticket['id']} • {chip} • {ticket['updated_at']} UTC", expanded=expanded):
                    st.markdown(f"**Query:**\n\n{ticket['query']}")
                    colb1, colb2, colb3, colb4 = st.columns([1,1,1,2])
                    with colb1:
                        st.caption(f"Labels: {', '.join(ticket.get('labels', [])) or '—'}")
                    with colb2:
                        st.caption(f"Priority: {ticket.get('priority','Medium')}")
                    with colb3:
                        st.caption(f"Assignee: {ticket.get('assigned_to','—') or '—'}")
                    with colb4:
                        if st.button("Copy link", key=f"{view_prefix}_tk_link_btn_{ticket['id']}"):
                            set_ticket_param(ticket["id"])
                            st.success("Link set in URL")
                    if ticket.get("replies"):
                        st.markdown("**Admin Replies:**")
                        for reply in ticket["replies"]:
                            st.markdown(f"- {reply['message']} (at {reply['created_at']} UTC)")
        else:
            st.write("No tickets available.")
        if has_more_local:
            if st.button("Load more", key=f"{view_prefix}_load_more"):
                st.session_state[page_key] += 1
                st.rerun()

    # Prepare sorted/filtered datasets
    keyw = st.session_state["ticket_search_pub"]
    data_open = filter_items(sorted([t for t in tickets_list if t["status"] != "Completed"], key=lambda x: x["created_at"], reverse=True), keyw, ["query","admin_notes","labels"])
    data_completed = filter_items(sorted([t for t in tickets_list if t["status"] == "Completed"], key=lambda x: x["updated_at"], reverse=True), keyw, ["query","admin_notes","labels"])
    data_all = filter_items(sorted(tickets_list, key=lambda x: x["created_at"], reverse=True), keyw, ["query","admin_notes","labels"])

    with t_open:
        render_ticket_list(data_open, "pub_tk_open")
    with t_completed:
        render_ticket_list(data_completed, "pub_tk_completed")
    with t_all:
        render_ticket_list(data_all, "pub_tk_all")

# =============== Admin Panel ===============
if st.session_state["logged_in"]:
    with tab_admin:
        st.header("🛠️ Admin Panel")

        # Bulk export
        colx1, colx2, colx3 = st.columns(3)
        with colx1:
            if st.button("Export Feedback CSV", key="adm_export_fb_btn"):
                csv_data = to_csv(feedback_list, ["id","message","created_at","updated_at","replies_count"])
                st.download_button("Download Feedback CSV", csv_data, "feedback.csv", "text/csv", key="adm_export_fb_dl")
        with colx2:
            if st.button("Export Tickets CSV", key="adm_export_tk_btn"):
                csv_data = to_csv(tickets_list, ["id","query","status","created_at","updated_at","replies_count"])
                st.download_button("Download Tickets CSV", csv_data, "tickets.csv", "text/csv", key="adm_export_tk_dl")
        with colx3:
            st.caption(f"GitHub ETags: FB {fb_headers.get('ETag','-')} • TK {tk_headers.get('ETag','-')}")

        st.markdown("---")
        st.subheader("Feedback Management")
        for fb in sorted(feedback_list, key=lambda x: x["created_at"], reverse=True):
            with st.expander(f"Feedback #{fb['id']}"):
                col1, col2 = st.columns([3,2])
                with col1:
                    edited_message = st.text_area("Edit feedback message:", fb["message"], key=f"adm_fb_edit_msg_{fb['id']}")
                with col2:
                    labels_val = st.text_input("Labels (comma-separated)", ",".join(fb.get("labels", [])), key=f"adm_fb_labels_{fb['id']}")
                    labels_list = [x.strip() for x in labels_val.split(",") if x.strip()]
                    priority = st.selectbox("Priority", ["Low","Medium","High"], index=["Low","Medium","High"].index(fb.get("priority","Medium")), key=f"adm_fb_pri_{fb['id']}")
                    assigned = st.text_input("Assignee", fb.get("assigned_to",""), key=f"adm_fb_assign_{fb['id']}")
                c1, c2, c3, c4 = st.columns(4)
                with c1:
                    if st.button("Save Feedback", key=f"adm_fb_save_btn_{fb['id']}"):
                        before = fb.copy()
                        fb["message"] = edited_message.strip()
                        fb["labels"] = labels_list
                        fb["priority"] = priority
                        fb["
