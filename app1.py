import streamlit as st
import requests
import base64
import json
import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

# --- GitHub API Setup ---
GITHUB_TOKEN = st.secrets["github_token"]
REPO = st.secrets["repo"]
BRANCH = st.secrets.get("branch", "main")

HEADERS = {
    "Authorization": f"token {GITHUB_TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

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
    if r.status_code in [200, 201]:
        return True
    else:
        st.error(f"Error updating {path} on GitHub: {r.status_code} {r.text}")
        return False

def load_feedback():
    data_str, sha = get_file_content("feedback.json")
    feedback_list = json.loads(data_str)
    for fb in feedback_list:
        if "replies" not in fb:
            fb["replies"] = []
        if "votes" not in fb:
            fb["votes"] = 0
    return feedback_list, sha

def load_tickets():
    data_str, sha = get_file_content("tickets.json")
    tickets_list = json.loads(data_str)
    for tk in tickets_list:
        if "replies" not in tk:
            tk["replies"] = []
        if "votes" not in tk:
            tk["votes"] = 0
        if "priority" not in tk:
            tk["priority"] = "Medium"
        if "attachments" not in tk:
            tk["attachments"] = []
    return tickets_list, sha

def save_feedback(feedback_list, sha):
    data_str = json.dumps(feedback_list, indent=2)
    return update_file_content("feedback.json", data_str, sha, "Update feedback data")

def save_tickets(tickets_list, sha):
    data_str = json.dumps(tickets_list, indent=2)
    return update_file_content("tickets.json", data_str, sha, "Update tickets data")

def remove_old_feedback(feedback_list):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    filtered = [
        fb for fb in feedback_list
        if datetime.strptime(fb["created_at"], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc) > cutoff
    ]
    return filtered

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

def convert_to_csv(data, fields):
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    for row in data:
        row_copy = row.copy()
        row_copy["replies_count"] = len(row_copy.get("replies", []))
        writer.writerow({k: row_copy.get(k, "") for k in fields})
    return output.getvalue()

# --- Initialize session state variables ---
if "tickets_sha" not in st.session_state:
    _, st.session_state["tickets_sha"] = load_tickets()
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

# --- Constants ---
FEEDBACK_CATEGORIES = ["All", "Academics", "Infrastructure", "Events", "Other"]
TICKET_CATEGORIES = ["All", "Academics", "Infrastructure", "Events", "Other"]
TICKET_STATUSES = ["All", "In Process", "Completed"]
TICKET_PRIORITIES = ["All", "Low", "Medium", "High"]

# --- Streamlit UI ---

st.set_page_config(page_title="AIKTC Anonymous Feedback", page_icon="📝", layout="wide")
st.title("📝 AIKTC Anonymous Feedback System")
st.markdown("Submit your feedback or queries anonymously. Your identity remains protected.")

anon_session_id = generate_session_id()

feedback_list, feedback_sha = load_feedback()
tickets_list, _ = load_tickets()

new_feedback_list = remove_old_feedback(feedback_list)
if len(new_feedback_list) < len(feedback_list):
    save_feedback(new_feedback_list, feedback_sha)
    feedback_list = new_feedback_list

# --- Sidebar Login/Logout with rerun inside handlers ---
st.sidebar.title("🔐 Admin Login")

if not st.session_state.get("logged_in", False):
    password = st.sidebar.text_input("Enter admin password:", type="password")
    if st.sidebar.button("Login"):
        if password == st.secrets["admin_password"]:
            st.session_state["logged_in"] = True
            st.session_state["login_error"] = False
            st.sidebar.success("Logged in successfully!")
            st.experimental_rerun()  # Rerun after login
        else:
            st.session_state["login_error"] = True
    if st.session_state.get("login_error", False):
        st.sidebar.error("❌ Incorrect password. Try again.")
else:
    st.sidebar.success("✅ Logged in as admin")
    if st.sidebar.button("Logout"):
        st.session_state["logged_in"] = False
        st.experimental_rerun()  # Rerun after logout

if st.session_state["logged_in"]:
    tab_public, tab_admin = st.tabs(["Public View", "Admin Panel"])
else:
    tab_public = st.container()

with tab_public:
    st.header("Anonymous Feedback")
    with st.form("feedback_form"):
        feedback_message = st.text_area("Write your feedback here:", "", height=100)
        feedback_category = st.selectbox("Select category:", FEEDBACK_CATEGORIES[1:])
        submitted_feedback = st.form_submit_button("Submit Feedback")

    if submitted_feedback:
        if feedback_message.strip():
            if st.session_state.get("last_feedback_msg", "") == feedback_message.strip():
                st.warning("You have already submitted this feedback in this session.")
            else:
                new_fb = {
                    "id": (max([fb["id"] for fb in feedback_list]) + 1) if feedback_list else 1,
                    "message": feedback_message.strip(),
                    "category": feedback_category,
                    "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                    "replies": [],
                    "votes": 0
                }
                feedback_list.append(new_fb)
                if save_feedback(feedback_list, feedback_sha):
                    st.success("✅ Feedback submitted successfully!")
                    st.session_state["last_feedback_msg"] = feedback_message.strip()
                else:
                    st.error("❌ Failed to save feedback.")
        else:
            st.error("❌ Please enter some feedback before submitting.")

    # --- Search and pagination for feedback ---
    def reset_feedback_page():
        st.session_state.feedback_page = 0

    st.header("View Submitted Feedback")
    col1, col2 = st.columns([3,1])
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
            FEEDBACK_CATEGORIES,
            key="feedback_category",
            on_change=reset_feedback_page
        )

    filtered_feedback = filter_items(
        feedback_list,
        st.session_state.feedback_search,
        ["message"],
        category=None if st.session_state.feedback_category == "All" else st.session_state.feedback_category
    )
    page_size = 5
    feedback_page = st.session_state.feedback_page
    page_items, has_more = paginate_items(filtered_feedback, feedback_page, page_size)

    if page_items:
        for fb in sorted(page_items, key=lambda x: x["created_at"], reverse=True):
            with st.expander(f"Feedback #{fb['id']} (Category: {fb.get('category','')}, Votes: {fb.get('votes',0)}) - Submitted: {fb['created_at']} UTC"):
                st.write(fb["message"])
                if fb.get("replies"):
                    st.markdown("**Admin Replies:**")
                    for reply in fb["replies"]:
                        st.markdown(f"- {reply['message']} (at {reply['created_at']} UTC)")
                # Voting buttons
                col_up, col_down = st.columns([1,1])
                with col_up:
                    if st.button(f"👍 Upvote Feedback #{fb['id']}", key=f"fb_upvote_{fb['id']}"):
                        fb["votes"] = fb.get("votes", 0) + 1
                        save_feedback(feedback_list, feedback_sha)
                        st.experimental_rerun()
                with col_down:
                    if st.button(f"👎 Downvote Feedback #{fb['id']}", key=f"fb_downvote_{fb['id']}"):
                        fb["votes"] = max(fb.get("votes", 0) - 1, 0)
                        save_feedback(feedback_list, feedback_sha)
                        st.experimental_rerun()
    else:
        st.write("No feedback submitted yet.")

    if has_more:
        if st.button("Load more feedback"):
            st.session_state.feedback_page += 1

    st.header("Submit a Ticket/Query")
    with st.form("ticket_form"):
        ticket_query = st.text_area("Write your query here:", "", height=100)
        ticket_category = st.selectbox("Select category:", TICKET_CATEGORIES[1:])
        ticket_priority = st.selectbox("Select priority:", TICKET_PRIORITIES[1:], index=1)
        ticket_file = st.file_uploader("Attach a file (optional)", type=["png", "jpg", "jpeg", "pdf", "txt"])
        submitted_ticket = st.form_submit_button("Submit Ticket")

    if submitted_ticket:
        if ticket_query.strip():
            if st.session_state.get("last_ticket_msg", "") == ticket_query.strip():
                st.warning("You have already submitted this ticket in this session.")
            else:
                new_id = (max([t["id"] for t in tickets_list]) + 1) if tickets_list else 1
                attachments = []
                if ticket_file is not None:
                    # Save file content as base64 string
                    file_content = ticket_file.read()
                    encoded_file = base64.b64encode(file_content).decode()
                    attachments.append({
                        "filename": ticket_file.name,
                        "content_base64": encoded_file,
                        "type": ticket_file.type
                    })
                new_ticket = {
                    "id": new_id,
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
                if save_tickets(tickets_list, st.session_state["tickets_sha"]):
                    st.success("✅ Ticket submitted successfully!")
                    _, new_sha = load_tickets()
                    st.session_state["tickets_sha"] = new_sha
                    st.session_state["last_ticket_msg"] = ticket_query.strip()
                else:
                    st.error("❌ Failed to save ticket.")
        else:
            st.error("❌ Please enter a query before submitting.")

    # --- Search and pagination for tickets ---
    def reset_ticket_page():
        st.session_state.ticket_page = 0

    st.header("View Tickets")
    col1, col2, col3, col4 = st.columns([3,1,1,1])
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
            TICKET_CATEGORIES,
            key="ticket_category",
            on_change=reset_ticket_page
        )
    with col3:
        st.selectbox(
            "Status filter:",
            TICKET_STATUSES,
            key="ticket_status",
            on_change=reset_ticket_page
        )
    with col4:
        st.selectbox(
            "Priority filter:",
            TICKET_PRIORITIES,
            key="ticket_priority",
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
    ticket_page = st.session_state.ticket_page
    page_items, has_more = paginate_items(filtered_tickets, ticket_page, page_size)

    if page_items:
        for ticket in sorted(page_items, key=lambda x: x["created_at"], reverse=True):
            if ticket["status"] != "Completed":
                with st.expander(f"Ticket #{ticket['id']} - {ticket['status']} - Priority: {ticket.get('priority','Medium')} - Votes: {ticket.get('votes',0)} (Created: {ticket['created_at']} UTC)"):
                    st.write(f"**Query:** {ticket['query']}")
                    st.write(f"Category: {ticket.get('category','')}")
                    st.write(f"Last Updated: {ticket['updated_at']} UTC")
                    if ticket.get("attachments"):
                        st.markdown("**Attachments:**")
                        for att in ticket["attachments"]:
                            st.markdown(f"- {att['filename']} ({att['type']})")
                    if ticket.get("replies"):
                        st.markdown("**Admin Replies:**")
                        for reply in ticket["replies"]:
                            st.markdown(f"- {reply['message']} (at {reply['created_at']} UTC)")
                    # Voting buttons
                    col_up, col_down = st.columns([1,1])
                    with col_up:
                        if st.button(f"👍 Upvote Ticket #{ticket['id']}", key=f"tk_upvote_{ticket['id']}"):
                            ticket["votes"] = ticket.get("votes", 0) + 1
                            save_tickets(tickets_list, st.session_state["tickets_sha"])
                            st.experimental_rerun()
                    with col_down:
                        if st.button(f"👎 Downvote Ticket #{ticket['id']}", key=f"tk_downvote_{ticket['id']}"):
                            ticket["votes"] = max(ticket.get("votes", 0) - 1, 0)
                            save_tickets(tickets_list, st.session_state["tickets_sha"])
                            st.experimental_rerun()
    else:
        st.write("No tickets submitted yet.")

    if has_more:
        if st.button("Load more tickets"):
            st.session_state.ticket_page += 1

if st.session_state["logged_in"]:
    with tab_admin:
        st.header("🛠️ Admin Panel - Manage Feedback and Tickets")

        feedback_list, feedback_sha = load_feedback()
        tickets_list, tickets_sha = load_tickets()
        st.session_state["tickets_sha"] = tickets_sha

        st.subheader("Export Data")
        if st.button("Export Feedback as CSV"):
            csv_data = convert_to_csv(feedback_list, ["id", "message", "category", "created_at", "votes", "replies_count"])
            st.download_button("
