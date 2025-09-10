import streamlit as st
import requests
import base64
import json
import io
import csv
import uuid
from datetime import datetime, timezone

# --- GitHub API Setup ---
GITHUB_TOKEN = st.secrets["github_token"]
REPO = st.secrets["repo"]
BRANCH = st.secrets.get("branch", "main")

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

# --- Constants ---
FEEDBACK_CATEGORIES = ["Academics", "Infrastructure", "Events", "Other"]
TICKET_CATEGORIES = ["Academics", "Infrastructure", "Events", "Other"]
TICKET_PRIORITIES = ["Low", "Medium", "High"]
TICKET_STATUSES = ["In Process", "Completed"]

PAGE_SIZE = 5

# --- GitHub file helpers ---

def get_file_content(path):
    url = f"https://api.github.com/repos/{REPO}/contents/{path}?ref={BRANCH}"
    r = requests.get(url, headers=HEADERS)
    if r.status_code == 200:
        content = r.json()
        sha = content["sha"]
        file_data = base64.b64decode(content["content"]).decode()
        return file_data, sha
    elif r.status_code == 404:
        return "[]", None
    else:
        st.error(f"Error fetching {path} from GitHub: {r.status_code} {r.text}")
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
    if r.status_code in [200, 201]:
        new_sha = r.json()["content"]["sha"]
        return True, new_sha
    else:
        st.error(f"Error updating {path} on GitHub: {r.status_code} {r.text}")
        return False, sha

# --- Load and save feedback ---

def load_feedback():
    data_str, sha = get_file_content("feedback.json")
    feedback_list = json.loads(data_str)
    for fb in feedback_list:
        fb.setdefault("replies", [])
        fb.setdefault("votes", 0)
        fb.setdefault("category", "Other")
    return feedback_list, sha

def save_feedback(feedback_list, sha):
    data_str = json.dumps(feedback_list, indent=2)
    success, new_sha = update_file_content("feedback.json", data_str, sha, "Update feedback data")
    if success:
        return new_sha
    else:
        return sha

# --- Load and save tickets ---

def load_tickets():
    data_str, sha = get_file_content("tickets.json")
    tickets_list = json.loads(data_str)
    for tk in tickets_list:
        tk.setdefault("replies", [])
        tk.setdefault("votes", 0)
        tk.setdefault("priority", "Medium")
        tk.setdefault("status", "In Process")
        tk.setdefault("category", "Other")
        tk.setdefault("attachments", [])
    return tickets_list, sha

def save_tickets(tickets_list, sha):
    data_str = json.dumps(tickets_list, indent=2)
    success, new_sha = update_file_content("tickets.json", data_str, sha, "Update tickets data")
    if success:
        return new_sha
    else:
        return sha

# --- Utility functions ---

def generate_session_id():
    if "anon_session_id" not in st.session_state:
        st.session_state["anon_session_id"] = str(uuid.uuid4())
    return st.session_state["anon_session_id"]

def filter_items(items, keyword, fields, category=None, status=None, priority=None):
    if not keyword and not category and not status and not priority:
        return items
    keyword_lower = keyword.lower() if keyword else None
    filtered = []
    for item in items:
        if category and item.get("category", "") != category:
            continue
        if status and item.get("status", "") != status:
            continue
        if priority and item.get("priority", "") != priority:
            continue
        if keyword_lower:
            matched = False
            for field in fields:
                if field in item and keyword_lower in item[field].lower():
                    matched = True
                    break
            if not matched:
                continue
        filtered.append(item)
    return filtered

def paginate_items(items, page, page_size):
    start = page * page_size
    end = start + page_size
    return items[start:end], len(items) > end

def sort_items(items, sort_key, reverse=False):
    if sort_key == "votes":
        return sorted(items, key=lambda x: x.get("votes", 0), reverse=reverse)
    elif sort_key == "date":
        return sorted(items, key=lambda x: x.get("created_at", ""), reverse=reverse)
    elif sort_key == "priority":
        priority_order = {"High": 3, "Medium": 2, "Low": 1}
        return sorted(items, key=lambda x: priority_order.get(x.get("priority", "Medium"), 2), reverse=reverse)
    else:
        return items

def convert_feedback_to_csv(feedback_list):
    output = io.StringIO()
    fieldnames = ["id", "message", "category", "created_at", "votes", "replies_count", "replies_details"]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for fb in feedback_list:
        replies = fb.get("replies", [])
        replies_str = "; ".join([f"{r['message']} ({r['created_at']})" for r in replies]) if replies else ""
        writer.writerow({
            "id": fb.get("id", ""),
            "message": fb.get("message", "").replace("\n", " "),
            "category": fb.get("category", ""),
            "created_at": fb.get("created_at", ""),
            "votes": fb.get("votes", 0),
            "replies_count": len(replies),
            "replies_details": replies_str
        })
    return output.getvalue()

def convert_tickets_to_csv(tickets_list):
    output = io.StringIO()
    fieldnames = [
        "id", "query", "category", "priority", "status",
        "created_at", "updated_at", "votes", "replies_count", "replies_details", "attachments_count", "attachments_filenames"
    ]
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for tk in tickets_list:
        replies = tk.get("replies", [])
        replies_str = "; ".join([f"{r['message']} ({r['created_at']})" for r in replies]) if replies else ""
        attachments = tk.get("attachments", [])
        attachments_filenames = ", ".join([att.get("filename", "") for att in attachments]) if attachments else ""
        writer.writerow({
            "id": tk.get("id", ""),
            "query": tk.get("query", "").replace("\n", " "),
            "category": tk.get("category", ""),
            "priority": tk.get("priority", ""),
            "status": tk.get("status", ""),
            "created_at": tk.get("created_at", ""),
            "updated_at": tk.get("updated_at", ""),
            "votes": tk.get("votes", 0),
            "replies_count": len(replies),
            "replies_details": replies_str,
            "attachments_count": len(attachments),
            "attachments_filenames": attachments_filenames
        })
    return output.getvalue()

# --- Initialize session state ---

if "tickets_sha" not in st.session_state:
    _, st.session_state["tickets_sha"] = load_tickets()
if "feedback_sha" not in st.session_state:
    _, st.session_state["feedback_sha"] = load_feedback()
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "login_error" not in st.session_state:
    st.session_state["login_error"] = False
if "feedback_page" not in st.session_state:
    st.session_state["feedback_page"] = 0
if "ticket_page" not in st.session_state:
    st.session_state["ticket_page"] = 0
if "feedback_search" not in st.session_state:
    st.session_state["feedback_search"] = ""
if "ticket_search" not in st.session_state:
    st.session_state["ticket_search"] = ""
if "feedback_category" not in st.session_state:
    st.session_state["feedback_category"] = "All"
if "ticket_category" not in st.session_state:
    st.session_state["ticket_category"] = "All"
if "ticket_status" not in st.session_state:
    st.session_state["ticket_status"] = "All"
if "ticket_priority" not in st.session_state:
    st.session_state["ticket_priority"] = "All"
if "feedback_sort" not in st.session_state:
    st.session_state["feedback_sort"] = "date"
if "ticket_sort" not in st.session_state:
    st.session_state["ticket_sort"] = "date"

# --- Streamlit UI ---

st.set_page_config(page_title="AIKTC Anonymous Feedback", page_icon="📝", layout="wide")
st.title("📝 AIKTC Anonymous Feedback System")
st.markdown("Submit your feedback or queries anonymously. Your identity remains protected.")

anon_session_id = generate_session_id()

feedback_list, feedback_sha = load_feedback()
tickets_list, tickets_sha = load_tickets()
st.session_state["feedback_sha"] = feedback_sha
st.session_state["tickets_sha"] = tickets_sha

# --- Sidebar Login/Logout ---

st.sidebar.title("🔐 Admin Login")

if not st.session_state.get("logged_in", False):
    password = st.sidebar.text_input("Enter admin password:", type="password")
    if st.sidebar.button("Login"):
        if password == st.secrets["admin_password"]:
            st.session_state["logged_in"] = True
            st.session_state["login_error"] = False
            st.sidebar.success("Logged in successfully!")
            st.experimental_rerun()
        else:
            st.session_state["login_error"] = True
    if st.session_state.get("login_error", False):
        st.sidebar.error("❌ Incorrect password. Try again.")
else:
    st.sidebar.success("✅ Logged in as admin")
    if st.sidebar.button("Logout"):
        st.session_state["logged_in"] = False
        st.experimental_rerun()

# --- Main content ---

if st.session_state["logged_in"]:
    tab_public, tab_admin = st.tabs(["Public View", "Admin Panel"])
else:
    tab_public = st.container()

with tab_public:
    st.header("Anonymous Feedback")
    with st.form("feedback_form"):
        feedback_message = st.text_area("Write your feedback here:", "", height=100)
        feedback_category = st.selectbox("Select category:", FEEDBACK_CATEGORIES)
        submitted_feedback = st.form_submit_button("Submit Feedback")

    if submitted_feedback:
        if feedback_message.strip():
            new_fb = {
                "id": (max([fb["id"] for fb in feedback_list]) + 1) if feedback_list else 1,
                "message": feedback_message.strip(),
                "category": feedback_category,
                "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                "replies": [],
                "votes": 0
            }
            feedback_list.append(new_fb)
            new_sha = save_feedback(feedback_list, st.session_state["feedback_sha"])
            if new_sha != st.session_state["feedback_sha"]:
                st.session_state["feedback_sha"] = new_sha
                st.success("✅ Feedback submitted successfully!")
            else:
                st.error("❌ Failed to save feedback.")
        else:
            st.error("❌ Please enter some feedback before submitting.")

    # --- Feedback search, filter, sort, pagination ---
    def reset_feedback_page():
        st.session_state.feedback_page = 0

    st.header("View Submitted Feedback")
    col1, col2, col3 = st.columns([3,1,2])
    with col1:
        st.text_input(
            "Search feedback:",
            key="feedback_search",
            on_change=reset_feedback_page,
            placeholder="Type to search feedback..."
        )
    with col2:
        st.selectbox(
            "Category filter:",
            ["All"] + FEEDBACK_CATEGORIES,
            key="feedback_category",
            on_change=reset_feedback_page
        )
    with col3:
        st.selectbox(
            "Sort by:",
            ["date", "votes"],
            key="feedback_sort",
            on_change=reset_feedback_page
        )

    filtered_feedback = filter_items(
        feedback_list,
        st.session_state.feedback_search,
        ["message"],
        category=None if st.session_state.feedback_category == "All" else st.session_state.feedback_category
    )
    sorted_feedback = sort_items(filtered_feedback, st.session_state.feedback_sort, reverse=True)
    page_items, has_more = paginate_items(sorted_feedback, st.session_state.feedback_page, PAGE_SIZE)

    if page_items:
        for fb in page_items:
            with st.expander(f"Feedback #{fb['id']} (Category: {fb.get('category','')}, Votes: {fb.get('votes',0)}) - Submitted: {fb['created_at']} UTC"):
                st.write(fb["message"])
                if fb.get("replies"):
                    st.markdown("**Admin Replies:**")
                    for reply in fb["replies"]:
                        st.markdown(f"- {reply['message']} (at {reply['created_at']} UTC)")
                col_up, col_down = st.columns([1,1])
                with col_up:
                    if st.button(f"👍 Upvote Feedback #{fb['id']}", key=f"fb_upvote_{fb['id']}"):
                        fb["votes"] = fb.get("votes", 0) + 1
                        new_sha = save_feedback(feedback_list, st.session_state["feedback_sha"])
                        if new_sha != st.session_state["feedback_sha"]:
                            st.session_state["feedback_sha"] = new_sha
                        st.experimental_rerun()
                with col_down:
                    if st.button(f"👎 Downvote Feedback #{fb['id']}", key=f"fb_downvote_{fb['id']}"):
                        fb["votes"] = max(fb.get("votes", 0) - 1, 0)
                        new_sha = save_feedback(feedback_list, st.session_state["feedback_sha"])
                        if new_sha != st.session_state["feedback_sha"]:
                            st.session_state["feedback_sha"] = new_sha
                        st.experimental_rerun()
    else:
        st.write("No feedback submitted yet.")

    if has_more:
        if st.button("Load more feedback"):
            st.session_state.feedback_page += 1

    st.header("Submit a Ticket/Query")
    with st.form("ticket_form"):
        ticket_query = st.text_area("Write your query here:", "", height=100)
        ticket_category = st.selectbox("Select category:", TICKET_CATEGORIES)
        ticket_priority = st.selectbox("Select priority:", TICKET_PRIORITIES, index=1)
        ticket_file = st.file_uploader("Attach a file (optional)", type=["png", "jpg", "jpeg", "pdf", "txt"])
        submitted_ticket = st.form_submit_button("Submit Ticket")

    if submitted_ticket:
        if ticket_query.strip():
            attachments = []
            if ticket_file is not None:
                file_content = ticket_file.read()
                encoded_file = base64.b64encode(file_content).decode()
                attachments.append({
                    "filename": ticket_file.name,
                    "content_base64": encoded_file,
                    "type": ticket_file.type
                })
            new_ticket = {
                "id": (max([t["id"] for t in tickets_list]) + 1) if tickets_list else 1,
                "query": ticket_query.strip(),
                "category": ticket_category,
                "priority": ticket_priority,
                "status": "In Process",
                "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                "replies": [],
                "votes": 0,
                "attachments": attachments
            }
            tickets_list.append(new_ticket)
            new_sha = save_tickets(tickets_list, st.session_state["tickets_sha"])
            if new_sha != st.session_state["tickets_sha"]:
                st.session_state["tickets_sha"] = new_sha
                st.success("✅ Ticket submitted successfully!")
            else:
                st.error("❌ Failed to save ticket.")
        else:
            st.error("❌ Please enter a query before submitting.")

    # --- Tickets search, filter, sort, pagination ---
    def reset_ticket_page():
        st.session_state.ticket_page = 0

    st.header("View Tickets")
    col1, col2, col3, col4, col5 = st.columns([3,1,1,1,2])
    with col1:
        st.text_input(
            "Search tickets:",
            key="ticket_search",
            on_change=reset_ticket_page,
            placeholder="Type to search tickets..."
        )
    with col2:
        st.selectbox(
            "Category filter:",
            ["All"] + TICKET_CATEGORIES,
            key="ticket_category",
            on_change=reset_ticket_page
        )
    with col3:
        st.selectbox(
            "Status filter:",
            ["All"] + TICKET_STATUSES,
            key="ticket_status",
            on_change=reset_ticket_page
        )
    with col4:
        st.selectbox(
            "Priority filter:",
            ["All"] + TICKET_PRIORITIES,
            key="ticket_priority",
            on_change=reset_ticket_page
        )
    with col5:
        st.selectbox(
            "Sort by:",
            ["date", "votes", "priority"],
            key="ticket_sort",
            on_change=reset_ticket_page
        )

    filtered_tickets = filter_items(
        tickets_list,
        st.session_state.ticket_search,
        ["query"],
        category=None if st.session_state.ticket_category == "All" else st.session_state.ticket_category,
        status=None if st.session_state.ticket_status == "All" else st.session_state.ticket_status,
        priority=None if st.session_state.ticket_priority == "All" else st.session_state.ticket_priority
    )
    sorted_tickets = sort_items(filtered_tickets, st.session_state.ticket_sort, reverse=True)
    page_items, has_more = paginate_items(sorted_tickets, st.session_state.ticket_page, PAGE_SIZE)

    if page_items:
        for ticket in page_items:
            with st.exp
