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
        fb.setdefault("replies", [])
    return feedback_list, sha

def save_feedback(feedback_list, sha):
    data_str = json.dumps(feedback_list, indent=2)
    return update_file_content("feedback.json", data_str, sha, "Update feedback data")

def load_tickets():
    data_str, sha = get_file_content("tickets.json")
    tickets_list = json.loads(data_str)
    for tk in tickets_list:
        tk.setdefault("replies", [])
    return tickets_list, sha

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
        row_copy = row.copy()
        row_copy["replies_count"] = len(row_copy.get("replies", []))
        writer.writerow({k: row_copy.get(k, "") for k in fields})
    return output.getvalue()

# Initialize session state
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

# UI Setup
st.set_page_config(page_title="AIKTC Anonymous Feedback", page_icon="📝", layout="wide")
st.title("📝 AIKTC Anonymous Feedback System")
st.markdown("Submit your feedback or queries anonymously. Your identity remains protected.")

anon_session_id = generate_session_id()

feedback_list, feedback_sha = load_feedback()
tickets_list, tickets_sha = load_tickets()
st.session_state["feedback_sha"] = feedback_sha
st.session_state["tickets_sha"] = tickets_sha

new_feedback_list = remove_old_feedback(feedback_list)
if len(new_feedback_list) < len(feedback_list):
    save_feedback(new_feedback_list, feedback_sha)
    feedback_list = new_feedback_list

# Sidebar Login
st.sidebar.title("🔐 Admin Login")
if not st.session_state.get("logged_in", False):
    password = st.sidebar.text_input("Enter admin password:", type="password")
    if st.sidebar.button("Login"):
        if password == st.secrets["admin_password"]:
            st.session_state["logged_in"] = True
            st.session_state["login_error"] = False
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

# Main Content
if st.session_state["logged_in"]:
    tab_public, tab_admin = st.tabs(["Public View", "Admin Panel"])
else:
    tab_public = st.container()

with tab_public:
    st.header("Anonymous Feedback")
    with st.form("feedback_form"):
        feedback_message = st.text_area("Write your feedback here:", "", height=100)
        submitted_feedback = st.form_submit_button("Submit Feedback")
    if submitted_feedback:
        if feedback_message.strip():
            new_fb = {
                "id": (max([fb["id"] for fb in feedback_list]) + 1) if feedback_list else 1,
                "message": feedback_message.strip(),
                "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                "replies": []
            }
            feedback_list.append(new_fb)
            if save_feedback(feedback_list, feedback_sha):
                st.success("✅ Feedback submitted!")
            else:
                st.error("❌ Failed to save feedback.")
        else:
            st.error("❌ Please enter some feedback.")

    # Feedback View
    st.header("View Submitted Feedback")
    st.text_input("Search feedback:", key="feedback_search", placeholder="Type to search feedback...")
    filtered_feedback = filter_items(feedback_list, st.session_state.feedback_search, ["message"])
    page_size = 5
    page_items, has_more = paginate_items(filtered_feedback, st.session_state.feedback_page, page_size)
    if page_items:
        for fb in sorted(page_items, key=lambda x: x["created_at"], reverse=True):
            with st.expander(f"Feedback #{fb['id']} (Submitted: {fb['created_at']} UTC)"):
                st.write(fb["message"])
                if fb.get("replies"):
                    st.markdown("**Admin Replies:**")
                    for reply in fb["replies"]:
                        st.markdown(f"- {reply['message']} (at {reply['created_at']} UTC)")
    else:
        st.write("No feedback available.")
    if has_more:
        if st.button("Load more feedback"):
            st.session_state.feedback_page += 1

    # Ticket Submission
    st.header("Submit a Ticket/Query")
    with st.form("ticket_form"):
        ticket_query = st.text_area("Write your query here:", "", height=100)
        submitted_ticket = st.form_submit_button("Submit Ticket")
    if submitted_ticket:
        if ticket_query.strip():
            new_ticket = {
                "id": (max([t["id"] for t in tickets_list]) + 1) if tickets_list else 1,
                "query": ticket_query.strip(),
                "status": "In Process",
                "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                "updated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
                "replies": []
            }
            tickets_list.append(new_ticket)
            if save_tickets(tickets_list, tickets_sha):
                st.success("✅ Ticket submitted!")
            else:
                st.error("❌ Failed to save ticket.")
        else:
            st.error("❌ Please enter a query.")

    # Ticket View
    st.header("View Tickets")
    st.text_input("Search tickets:", key="ticket_search", placeholder="Type to search tickets...")
    filtered_tickets = filter_items(tickets_list, st.session_state.ticket_search, ["query"])
    page_items, has_more = paginate_items(filtered_tickets, st.session_state.ticket_page, page_size)
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
        st.write("No tickets available.")
    if has_more:
        if st.button("Load more tickets"):
            st.session_state.ticket_page += 1

if st.session_state["logged_in"]:
    with tab_admin:
        st.header("🛠️ Admin Panel")
        st.subheader("Manage Feedback and Tickets")
        feedback_list, feedback_sha = load_feedback()
        tickets_list, tickets_sha = load_tickets()
        st.session_state["tickets_sha"] = tickets_sha
        if st.button("Export Feedback as CSV"):
            csv_data = convert_to_csv(feedback_list, ["id", "message", "created_at", "replies_count"])
            st.download_button("Download Feedback CSV", csv_data, "feedback.csv", "text/csv")
        if st.button("Export Tickets as CSV"):
            csv_data = convert_to_csv(tickets_list, ["id", "query", "status", "created_at", "updated_at", "replies_count"])
            st.download_button("Download Tickets CSV", csv_data, "tickets.csv", "text/csv")
        st.markdown("---")
        st.subheader("Feedback Management")
        if feedback_list:
            for fb in sorted(feedback_list, key=lambda x: x["created_at"], reverse=True):
                with st.expander(f"Feedback #{fb['id']}"):
                    edited_message = st.text_area("Edit feedback message:", fb["message"], key=f"fb_edit_{fb['id']}")
                    if st.button("Save Feedback", key=f"fb_save_{fb['id']}"):
                        fb["message"] = edited_message.strip()
                        if save_feedback(feedback_list, feedback_sha):
                            st.success("✅ Feedback saved.")
                        else:
                            st.error("❌ Failed to save feedback.")
                    if st.button("Delete Feedback", key=f"fb_del_{fb['id']}"):
                        feedback_list.remove(fb)
                        if save_feedback(feedback_list, feedback_sha):
                            st.success("✅ Feedback deleted.")
                        else:
                            st.error("❌ Failed to delete feedback.")
                    with st.form(f"fb_reply_form_{fb['id']}"):
                        reply_text = st.text_area("Write a reply:", "", key=f"fb_reply_text_{fb['id']}")
                        if st.form_submit_button("Submit Reply"):
                            if reply_text.strip():
                                reply = {
                                    "message": reply_text.strip(),
                                    "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
                                }
                                fb.setdefault("replies", []).append(reply)
                                if save_feedback(feedback_list, feedback_sha):
                                    st.success("✅ Reply added.")
                                else:
                                    st.error("❌ Failed to add reply.")
        else:
            st.write("No feedback available.")

        st.markdown("---")
        st.subheader("Ticket Management")
        if tickets_list:
            for ticket in sorted(tickets_list, key=lambda x: x["created_at"], reverse=True):
                with st.expander(f"Ticket #{ticket['id']} - {ticket['status']}"):
                    edited_query = st.text_area("Edit ticket query:", ticket["query"], key=f"tk_edit_{ticket['id']}")
                    new_status = st.selectbox("Update status:", ["In Process", "Completed"], index=0 if ticket["status"] == "In Process" else 1, key=f"tk_status_{ticket['id']}")
                    if st.button("Save Ticket", key=f"tk_save_{ticket['id']}"):
                        ticket["query"] = edited_query.strip()
                        ticket["status"] = new_status
                        ticket["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
                        if save_tickets(tickets_list, tickets_sha):
                            st.success("✅ Ticket saved.")
                        else:
                            st.error("❌ Failed to save ticket.")
                    if st.button("Delete Ticket", key=f"tk_del_{ticket['id']}"):
                        tickets_list.remove(ticket)
                        if save_tickets(tickets_list, tickets_sha):
                            st.success("✅ Ticket deleted.")
                        else:
                            st.error("❌ Failed to delete ticket.")
                    with st.form(f"tk_reply_form_{ticket['id']}"):
                        reply_text = st.text_area("Write a reply:", "", key=f"tk_reply_text_{ticket['id']}")
                        if st.form_submit_button("Submit Reply"):
                            if reply_text.strip():
                                reply = {
                                    "message": reply_text.strip(),
                                    "created_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S")
                                }
                                ticket.setdefault("replies", []).append(reply)
                                if save_tickets(tickets_list, tickets_sha):
                                    st.success("✅ Reply added.")
                                else:
                                    st.error("❌ Failed to add reply.")
