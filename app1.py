import streamlit as st
import requests
import base64
import json
import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

# =========================
# App Setup & Config
# =========================
st.set_page_config(page_title="AIKTC Anonymous Feedback", page_icon="📝", layout="wide")
st.title("📝 AIKTC Anonymous Feedback System")
st.markdown("Submit feedback or queries anonymously. Identity remains protected. Be respectful and constructive.")

# Secrets
GITHUB_TOKEN = st.secrets["github_token"]
REPO = st.secrets["repo"]                 # e.g., "owner/repo"
BRANCH = st.secrets.get("branch", "main")
ADMIN_PASSWORD = st.secrets["admin_password"]

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

# =========================
# Utilities
# =========================
def now_utc_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")

def parse_utc(s):
    # stored without timezone suffix; treat as UTC
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)

def generate_session_id():
    if "anon_session_id" not in st.session_state:
        st.session_state["anon_session_id"] = str(uuid.uuid4())
    return st.session_state["anon_session_id"]

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

def update_file_content(path, data_str, sha, commit_message):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}"
    encoded_content = base64.b64encode(data_str.encode()).decode()
    payload = {
        "message": commit_message,
        "content": encoded_content,
        "branch": BRANCH
    }
    if sha:
        payload["sha"] = sha
    r = requests.put(url, headers=HEADERS, json=payload)
    return r

def load_json_list(path):
    data_str, sha, headers = get_file_content(path)
    try:
        items = json.loads(data_str)
    except Exception:
        items = []
    # normalize structure
    for it in items:
        it.setdefault("replies", [])
        it.setdefault("labels", [])
        it.setdefault("priority", "Medium")
        it.setdefault("assigned_to", "")
        it.setdefault("admin_notes", "")
        it.setdefault("reactions", {"like": 0, "helpful": 0, "agree": 0})
        it.setdefault("deleted_at", None)
        it.setdefault("history", [])
    return items, sha, headers

def save_json_list(path, items, sha, commit_message):
    data_str = json.dumps(items, indent=2)
    r = update_file_content(path, data_str, sha, commit_message)
    return r

def optimistic_save(path, items, old_sha, commit_message, id_key="id"):
    # Try save; on 409 or 422, refetch, merge by id, retry once
    r = save_json_list(path, items, old_sha, commit_message)
    if r.status_code in (200, 201):
        return True, r
    if r.status_code in (409, 422):
        latest_str, latest_sha, _ = get_file_content(path)
        try:
            latest = json.loads(latest_str)
        except Exception:
            latest = []
        # build index
        by_id = {it[id_key]: it for it in latest if id_key in it}
        for it in items:
            iid = it.get(id_key)
            if iid is None:
                continue
            if iid not in by_id:
                by_id[iid] = it
            else:
                # prefer newer updated_at if present; merge replies
                a = by_id[iid]
                b = it
                a_ts = parse_utc(a.get("updated_at", a.get("created_at", now_utc_str())))
                b_ts = parse_utc(b.get("updated_at", b.get("created_at", now_utc_str())))
                merged = a if a_ts >= b_ts else b
                # merge replies union
                rep_a = a.get("replies", [])
                rep_b = b.get("replies", [])
                merged["replies"] = rep_a + [r for r in rep_b]
                # merge reactions by summation
                ra = a.get("reactions", {"like":0,"helpful":0,"agree":0})
                rb = b.get("reactions", {"like":0,"helpful":0,"agree":0})
                merged["reactions"] = {
                    "like": int(ra.get("like",0)) + int(rb.get("like",0)),
                    "helpful": int(ra.get("helpful",0)) + int(rb.get("helpful",0)),
                    "agree": int(ra.get("agree",0)) + int(rb.get("agree",0)),
                }
                by_id[iid] = merged
        merged_list = list(by_id.values())
        r2 = save_json_list(path, merged_list, latest_sha, commit_message + " (merge)")
        if r2.status_code in (200, 201):
            return True, r2
        return False, r2
    st.error(f"Save failed: {r.status_code} {r.text}")
    return False, r

def filter_items(items, keyword, fields, status=None, labels=None, date_range=None, include_deleted=False):
    out = []
    kw = (keyword or "").lower().strip()
    for it in items:
        if it.get("deleted_at") and not include_deleted:
            continue
        if status and it.get("status") != status:
            continue
        if labels:
            if not set(labels).issubset(set(it.get("labels", []))):
                continue
        if date_range:
            dt = parse_utc(it.get("updated_at", it.get("created_at")))
            if not (date_range <= dt <= date_range[20]):
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
        # also search replies
        for rp in it.get("replies", []):
            hay.append(str(rp.get("message","")).lower())
        if any(kw in h for h in hay):
            out.append(it)
    return out

def paginate_items(items, page, page_size):
    start = page * page_size
    end = start + page_size
    return items[start:end], len(items) > end

def convert_to_csv(data, fields):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in data:
        row_copy = row.copy()
        row_copy["replies_count"] = len(row_copy.get("replies", []))
        writer.writerow({k: row_copy.get(k, "") for k in fields})
    return output.getvalue()

def mask_pii(text):
    import re
    if not text:
        return text
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
        "action": action,
        "author": author,
        "at": now_utc_str(),
        "before": before,
        "after": after,
    })

# =========================
# Load Data
# =========================
anon_session_id = generate_session_id()

feedback_list, feedback_sha, fb_headers = load_json_list("feedback.json")
tickets_list, tickets_sha, tk_headers = load_json_list("tickets.json")

# Clean old public feedback (24h window for public view only)
def remove_old_feedback_window(fb):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    return [x for x in fb if parse_utc(x["created_at"]) > cutoff]

# =========================
# Sidebar: Admin Login + Filters
# =========================
st.sidebar.title("🔐 Admin")
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "login_error" not in st.session_state:
    st.session_state["login_error"] = False

if not st.session_state["logged_in"]:
    pwd = st.sidebar.text_input("Enter admin password:", type="password")
    if st.sidebar.button("Login"):
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
    if st.sidebar.button("Logout"):
        st.session_state["logged_in"] = False
        st.rerun()

st.sidebar.markdown("---")
st.sidebar.subheader("Quick Filters")
default_labels = ["General","Facility","IT","Event","Academics"]
label_filter = st.sidebar.multiselect("Filter by labels", default_labels, [])
priority_filter = st.sidebar.multiselect("Priority", ["Low","Medium","High"], [])
show_completed = st.sidebar.checkbox("Show Completed Tickets", True)

# =========================
# Query Params: Deep Links
# =========================
qp = st.query_params.to_dict()
deep_ticket_id = int(qp.get("t", 0)) if qp.get("t") else None
deep_feedback_id = int(qp.get("fb", 0)) if qp.get("fb") else None

def set_ticket_param(i):
    st.query_params.t = str(i)

def set_feedback_param(i):
    st.query_params.fb = str(i)

# =========================
# Tabs: Public / Admin
# =========================
if st.session_state["logged_in"]:
    tab_public, tab_admin = st.tabs(["Public View", "Admin Panel"])
else:
    tab_public = st.container()

# =========================
# PUBLIC VIEW
# =========================
with tab_public:
    st.header("Anonymous Feedback")
    with st.form("feedback_form"):
        feedback_message = st.text_area("Write your feedback (Markdown supported):", "", height=100, help="Avoid personal info. Basic Markdown is supported.")
        colf1, colf2 = st.columns([1,1])
        with colf1:
            st.caption("Preview:")
            st.markdown(feedback_message or "_Nothing yet_")
        with colf2:
            st.caption("Tips: Use # for headings, **bold**, - bullets.")
        submitted_feedback = st.form_submit_button("Submit Feedback")

    if submitted_feedback:
        ok, wait = throttle_ok("fb_throttle", limit_seconds=30, max_hourly=5)
        if not ok:
            st.error(f"Rate limit: wait {wait} seconds or try later.")
        elif feedback_message.strip():
            new_fb = {
                "id": (max([fb["id"] for fb in feedback_list]) + 1) if feedback_list else 1,
                "message": mask_pii(feedback_message.strip()),
                "created_at": now_utc_str(),
                "updated_at": now_utc_str(),
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
            ok_save, resp = optimistic_save("feedback.json", feedback_list, feedback_sha, "Add feedback")
            if ok_save:
                st.success("✅ Feedback submitted!")
                st.query_params.fb = str(new_fb["id"])
                st.rerun()
            else:
                st.error("❌ Failed to save feedback.")
        else:
            st.error("❌ Please enter some feedback.")

    # Feedback list (last 24h public view)
    st.subheader("Recent Feedback")
    st.text_input("Search feedback:", key="feedback_search", placeholder="Type to search feedback...")
    public_feedback = remove_old_feedback_window(feedback_list)
    filtered_feedback = filter_items(public_feedback, st.session_state.get("feedback_search",""), ["message","admin_notes","labels"])
    page_size = 5
    if "feedback_page" not in st.session_state:
        st.session_state["feedback_page"] = 0
    page_items, has_more = paginate_items(sorted(filtered_feedback, key=lambda x: x["created_at"], reverse=True), st.session_state["feedback_page"], page_size)

    if page_items:
        for fb in page_items:
            expanded = (deep_feedback_id == fb["id"])
            with st.expander(f"Feedback #{fb['id']} • {fb['created_at']} UTC", expanded=expanded):
                st.markdown(fb["message"])
                colx1, colx2, colx3, colx4 = st.columns([1,1,1,3])
                with colx1:
                    if st.button(f"👍 {fb['reactions'].get('like',0)}", key=f"fb_like_{fb['id']}"):
                        fb["reactions"]["like"] = fb["reactions"].get("like",0)+1
                        fb["updated_at"] = now_utc_str()
                        optimistic_save("feedback.json", feedback_list, feedback_sha, "React feedback")
                        st.rerun()
                with colx2:
                    if st.button(f"✅ {fb['reactions'].get('helpful',0)}", key=f"fb_helpful_{fb['id']}"):
                        fb["reactions"]["helpful"] = fb["reactions"].get("helpful",0)+1
                        fb["updated_at"] = now_utc_str()
                        optimistic_save("feedback.json", feedback_list, feedback_sha, "React feedback")
                        st.rerun()
                with colx3:
                    if st.button(f"🙌 {fb['reactions'].get('agree',0)}", key=f"fb_agree_{fb['id']}"):
                        fb["reactions"]["agree"] = fb["reactions"].get("agree",0)+1
                        fb["updated_at"] = now_utc_str()
                        optimistic_save("feedback.json", feedback_list, feedback_sha, "React feedback")
                        st.rerun()
                with colx4:
                    if st.button("Copy link", key=f"fb_link_{fb['id']}"):
                        set_feedback_param(fb["id"])
                        st.success("Link set in URL")
                if fb.get("replies"):
                    st.markdown("**Admin Replies:**")
                    for reply in fb["replies"]:
                        st.markdown(f"- {reply['message']} (at {reply['created_at']} UTC)")
    else:
        st.write("No feedback available.")
    if has_more:
        if st.button("Load more feedback"):
            st.session_state["feedback_page"] += 1
            st.rerun()

    # Tickets (Public submission)
    st.header("Submit a Ticket/Query")
    with st.form("ticket_form"):
        ticket_query = st.text_area("Write your query (Markdown supported):", "", height=100)
        colp1, colp2 = st.columns([1,1])
        with colp1:
            st.caption("Preview:")
            st.markdown(ticket_query or "_Nothing yet_")
        with colp2:
            priority_new = st.selectbox("Priority", ["Low","Medium","High"], index=1)
        submitted_ticket = st.form_submit_button("Submit Ticket")
    if submitted_ticket:
        ok, wait = throttle_ok("tk_throttle", limit_seconds=30, max_hourly=5)
        if not ok:
            st.error(f"Rate limit: wait {wait} seconds or try later.")
        elif ticket_query.strip():
            new_ticket = {
                "id": (max([t["id"] for t in tickets_list]) + 1) if tickets_list else 1,
                "query": mask_pii(ticket_query.strip()),
                "status": "In Process",
                "created_at": now_utc_str(),
                "updated_at": now_utc_str(),
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
            ok_save, resp = optimistic_save("tickets.json", tickets_list, tickets_sha, "Add ticket")
            if ok_save:
                st.success("✅ Ticket submitted!")
                st.query_params.t = str(new_ticket["id"])
                st.rerun()
            else:
                st.error("❌ Failed to save ticket.")
        else:
            st.error("❌ Please enter a query.")

    # Ticket Views: Open / Completed / All
    st.header("View Tickets")
    t1, t2, t3 = st.tabs(["Open", "Completed", "All"])
    st.text_input("Search tickets:", key="ticket_search", placeholder="Type to search tickets...")

    def render_ticket_list(data, tab, title_suffix=""):
        page_key = f"ticket_page_{title_suffix or 'default'}"
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
                        if st.button("Copy link", key=f"tk_link_{ticket['id']}"):
                            set_ticket_param(ticket["id"])
                            st.success("Link set in URL")
                    if ticket.get("replies"):
                        st.markdown("**Admin Replies:**")
                        for reply in ticket["replies"]:
                            st.markdown(f"- {reply['message']} (at {reply['created_at']} UTC)")
        else:
            st.write("No tickets available.")
        if has_more_local:
            if st.button("Load more", key=f"load_more_{title_suffix or 'default'}"):
                st.session_state[page_key] += 1
                st.rerun()

    # Prepare filtered datasets
    keyw = st.session_state.get("ticket_search","")
    # Open
    data_open = filter_items(
        sorted([t for t in tickets_list if t["status"] != "Completed"], key=lambda x: x["created_at"], reverse=True),
        keyw, ["query","admin_notes","labels"]
    )
    # Completed
    data_completed = filter_items(
        sorted([t for t in tickets_list if t["status"] == "Completed"], key=lambda x: x["updated_at"], reverse=True),
        keyw, ["query","admin_notes","labels"]
    )
    # All
    data_all = filter_items(
        sorted(tickets_list, key=lambda x: x["created_at"], reverse=True),
        keyw, ["query","admin_notes","labels"]
    )

    with t1:
        render_ticket_list(data_open, t1, "open")
    with t2:
        render_ticket_list(data_completed, t2, "completed")
    with t3:
        render_ticket_list(data_all, t3, "all")

# =========================
# ADMIN PANEL
# =========================
if st.session_state.get("logged_in", False):
    with tab_admin:
        st.header("🛠️ Admin Panel")
        st.subheader("Bulk Tools")
        colu1, colu2, colu3, colu4 = st.columns(4)
        with colu1:
            if st.button("Export Feedback CSV"):
                csv_data = convert_
