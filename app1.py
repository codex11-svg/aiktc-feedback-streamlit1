import streamlit as st
import requests
import base64
import json
import csv
import io
import uuid
from datetime import datetime, timedelta, timezone

# --- Safe rerun mechanism ---
if st.session_state.get("needs_rerun", False):
    st.session_state["needs_rerun"] = False
    st.rerun()

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
    # Ensure replies field exists
    for fb in feedback_list:
        if "replies" not in fb:
            fb["replies"] = []
    return feedback_list, sha

def load_tickets():
    data_str, sha = get_file_content("tickets.json")
    tickets_list = json.loads(data_str)
    # Ensure replies field exists
    for tk in tickets_list:
        if "replies" not in tk:
            tk["replies"] = []
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

def filter_items(items, keyword, fields):
    if not keyword:
        return items
    keyword_lower = keyword.lower()
    filtered = []
    for item in items:
        for field in fields:
            if field in item and keyword_lower in item[field].lower():
                filtered.append(item)
                break
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
        # Flatten replies count for CSV
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

# --- Streamlit UI ---

st.set_page_config(page_title="AIKTC Anonymous Feedback", page_icon="📝", layout="wide")
st.title("📝 AIKTC Anonymous Feedback System")
st.markdown("Submit your feedback or queries anonymously. Your identity remains protected.")

# Generate anonymous session ID
anon_session_id = generate_session_id()

# Load data
feedback_list, feedback_sha = load_feedback()
tickets_list, _ = load_tickets()

# Remove feedback older than 24 hours
new_feedback_list = remove_old_feedback(feedback_list)
if len(new_feedback_list) < len(feedback_list):
    save_feedback(new_feedback_list, feedback_sha)
    feedback_list = new_feedback_list

# --- Sidebar Admin Login ---
st.sidebar.title("🔐 Admin Login")

if not st.session_state["logged_in"]:
    password = st.sidebar.text_input("Enter admin password:", type="password")
    if st.sidebar.button("Login"):
        if password == st.secrets["admin_password"]:
            st.session_state["logged_in"] = True
            st.session_state["login_error"] = False
            st.sidebar.success("Logged in successfully!")
            st.session_state["needs_rerun"] = True
        else:
            st.session_state["login_error"] = True
    if st.session_state["login_error"]:
        st.sidebar.error("❌ Incorrect password. Try again.")
else:
    st.sidebar.success("✅ Logged in as admin")
    if st.sidebar.button("Logout"):
        st.session_state["logged_in"] = False
        st.session_state["needs_rerun"] = True

# --- Tabs for Public and Admin views ---
if st.session_state["logged_in"]:
    tab_public, tab_admin = st.tabs(["Public View", "Admin Panel"])
else:
    tab_public = st.container()  # just a container for public view

# --- PUBLIC VIEW ---
with tab_public:
    # --- Public Feedback Submission ---
    st.header("Anonymous Feedback")
    with st.form("feedback_form"):
        feedback_message = st.text_area("Write your feedback here:", "", height=100)
        submitted_feedback = st.form_submit_button("Submit Feedback")

    if submitted_feedback:
        if feedback_message.strip():
            # Prevent duplicate submission in same session
            if st.session_state.get("last_feedback_msg", "") == feedback_message.strip():
                st.warning("You have already submitted this feedback in this session.")
            else:
                new_fb = {
                    "id": (max([fb["id"] for fb in feedback_list]) + 1) if feedback_list else 1,
                    "message": feedback_message.strip(),
                    "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                    "replies": []
                }
                feedback_list.append(new_fb)
                if save_feedback(feedback_list, feedback_sha):
                    st.success("✅ Feedback submitted successfully!")
                    st.session_state["last_feedback_msg"] = feedback_message.strip()
                else:
                    st.error("❌ Failed to save feedback.")
        else:
            st.error("❌ Please enter some feedback before submitting.")

    # --- Public Feedback Display with Search and Pagination ---
    st.header("View Submitted Feedback")
    st.text_input("Search feedback:", key="feedback_search", on_change=lambda: st.session_state.update(feedback_page=0))
    filtered_feedback = filter_items(feedback_list, st.session_state.feedback_search, ["message"])
    page_size = 5
    feedback_page = st.session_state.feedback_page
    page_items, has_more = paginate_items(filtered_feedback, feedback_page, page_size)

    if page_items:
        for fb in sorted(page_items, key=lambda x: x["created_at"], reverse=True):
            with st.expander(f"Feedback #{fb['id']} (Submitted: {fb['created_at']} UTC)"):
                st.write(fb["message"])
                if fb.get("replies"):
                    st.markdown("**Admin Replies:**")
                    for reply in fb["replies"]:
                        st.markdown(f"- {reply['message']} (at {reply['created_at']} UTC)")
    else:
        st.write("No feedback submitted yet.")

    if has_more:
        if st.button("Load more feedback"):
            st.session_state.feedback_page += 1

    # --- Public Ticket Submission ---
    st.header("Submit a Ticket/Query")
    with st.form("ticket_form"):
        ticket_query = st.text_area("Write your query here:", "", height=100)
        submitted_ticket = st.form_submit_button("Submit Ticket")

    if submitted_ticket:
        if ticket_query.strip():
            if st.session_state.get("last_ticket_msg", "") == ticket_query.strip():
                st.warning("You have already submitted this ticket in this session.")
            else:
                new_id = (max([t["id"] for t in tickets_list]) + 1) if tickets_list else 1
                new_ticket = {
                    "id": new_id,
                    "query": ticket_query.strip(),
                    "status": "In Process",
                    "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                    "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                    "replies": []
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

    # --- Public Ticket Display with Search and Pagination ---
    st.header("View Tickets")
    st.text_input("Search tickets:", key="ticket_search", on_change=lambda: st.session_state.update(ticket_page=0))
    filtered_tickets = filter_items(tickets_list, st.session_state.ticket_search, ["query"])
    ticket_page = st.session_state.ticket_page
    page_items, has_more = paginate_items(filtered_tickets, ticket_page, page_size)

    if page_items:
        for ticket in sorted(page_items, key=lambda x: x["created_at"], reverse=True):
            if ticket["status"] != "Completed":
                with st.expander(f"Ticket #{ticket['id']} - {ticket['status']} (Created: {ticket['created_at']} UTC)"):
                    st.write(f"**Query:** {ticket['query']}")
                    st.write(f"Last Updated: {ticket['updated_at']} UTC")
                    if ticket.get("replies"):
                        st.markdown("**Admin Replies:**")
                        for reply in ticket["replies"]:
                            st.markdown(f"- {reply['message']} (at {reply['created_at']} UTC)")
    else:
        st.write("No tickets submitted yet.")

    if has_more:
        if st.button("Load more tickets"):
            st.session_state.ticket_page += 1

# --- ADMIN PANEL ---
if st.session_state["logged_in"]:
    with tab_admin:
        st.header("🛠️ Admin Panel - Manage Feedback and Tickets")

        # Reload fresh data and SHAs for admin actions
        feedback_list, feedback_sha = load_feedback()
        tickets_list, tickets_sha = load_tickets()
        st.session_state["tickets_sha"] = tickets_sha

        # --- Export Data ---
        st.subheader("Export Data")
        if st.button("Export Feedback as CSV"):
            csv_data = convert_to_csv(feedback_list, ["id", "message", "created_at", "replies_count"])
            st.download_button("Download Feedback CSV", csv_data, "feedback.csv", "text/csv")
        if st.button("Export Tickets as CSV"):
            csv_data = convert_to_csv(tickets_list, ["id", "query", "status", "created_at", "updated_at", "replies_count"])
            st.download_button("Download Tickets CSV", csv_data, "tickets.csv", "text/csv")

        st.markdown("---")

        # --- Feedback Management ---
        st.subheader("Feedback Management")
        if feedback_list:
            for fb in sorted(feedback_list, key=lambda x: x["created_at"], reverse=True):
                with st.expander(f"Feedback #{fb['id']} (Submitted: {fb['created_at']} UTC)", expanded=False):
                    edited_message = st.text_area("Edit feedback message:", fb["message"], key=f"fb_edit_{fb['id']}")
                    col1, col2, col3 = st.columns([1,1,2])
                    with col1:
                        if st.button("Save Feedback", key=f"fb_save_{fb['id']}"):
                            fb["message"] = edited_message.strip()
                            if save_feedback(feedback_list, feedback_sha):
                                st.success("✅ Feedback saved.")
                                st.session_state["needs_rerun"] = True
                            else:
                                st.error("❌ Failed to save feedback.")
                    with col2:
                        delete_key = f"fb_del_confirm_{fb['id']}"
                        if st.session_state.get(delete_key, False):
                            if st.button(f"Confirm Delete Feedback #{fb['id']}", key=f"fb_del_confirm_btn_{fb['id']}"):
                                feedback_list = [f for f in feedback_list if f["id"] != fb["id"]]
                                st.session_state[delete_key] = False
                                st.session_state["needs_rerun"] = True
                                success = save_feedback(feedback_list, feedback_sha)
                                if success:
                                    st.success("✅ Feedback deleted.")
                                else:
                                    st.error("❌ Failed to delete feedback.")
                        else:
                            if st.button(f"Delete Feedback #{fb['id']}", key=f"fb_del_{fb['id']}"):
                                st.session_state[delete_key] = True
                                st.session_state["needs_rerun"] = True
                    with col3:
                        # Admin reply form
                        with st.form(f"fb_reply_form_{fb['id']}"):
                            reply_text = st.text_area("Write a reply to this feedback:", key=f"fb_reply_text_{fb['id']}", height=80)
                            submitted_reply = st.form_submit_button("Submit Reply")
                            if submitted_reply:
                                if reply_text.strip():
                                    reply = {
                                        "message": reply_text.strip(),
                                        "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
                                    }
                                    fb.setdefault("replies", []).append(reply)
                                    if save_feedback(feedback_list, feedback_sha):
                                        st.success("✅ Reply saved.")
                                        st.session_state["needs_rerun"] = True
                                    else:
                                        st.error("❌ Failed to save reply.")
                                else:
                                    st.error("❌ Reply cannot be empty.")

        else:
            st.write("No feedback available.")

        st.markdown("---")

        # --- Ticket Management ---
        st.subheader("Ticket Management")
        if tickets_list:
            for ticket in sorted(tickets_list, key=lambda x: x["created_at"], reverse=True):
                with st.expander(f"Ticket #{ticket['id']} - {ticket['status']} (Created: {ticket['created_at']} UTC)", expanded=False):
                    edited_query = st.text_area("Edit ticket query:", ticket["query"], key=f"tk_edit_{ticket['id']}")
                    new_status = st.selectbox("Update Status:", ["In Process", "Completed"], index=0 if ticket["status"]=="In Process" else 1, key=f"tk_status_{ticket['id']}")
                    col1, col2, col3, col4 = st.columns([1,1,1,2])
                    with col1:
                        if st.button("Save Ticket", key=f"tk_save_{ticket['id']}"):
                            ticket["query"] = edited_query.strip()
                            ticket["status"] = new_status
                            ticket["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
                            if save_tickets(tickets_list, tickets_sha):
                                st.success("✅ Ticket saved.")
                                st.session_state["needs_rerun"] = True
                            else:
                                st.error("❌ Failed to save ticket.")
                    with col2:
                        delete_key = f"tk_del_confirm_{ticket['id']}"
                        if st.session_state.get(delete_key, False):
                            if st.button(f"Confirm Delete Ticket #{ticket['id']}", key=f"tk_del_confirm_btn_{ticket['id']}"):
                                tickets_list = [t for t in tickets_list if t["id"] != ticket["id"]]
                                st.session_state[delete_key] = False
                                st.session_state["needs_rerun"] = True
                                success = save_tickets(tickets_list, tickets_sha)
                                if success:
                                    st.success("✅ Ticket deleted.")
                                else:
                                    st.error("❌ Failed to delete ticket.")
                        else:
                            if st.button(f"Delete Ticket #{ticket['id']}", key=f"tk_del_{ticket['id']}"):
                                st.session_state[delete_key] = True
                                st.session_state["needs_rerun"] = True
                    with col3:
