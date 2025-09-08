import streamlit as st
import requests
import base64
import json
from datetime import datetime, timedelta

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
    return feedback_list, sha

def load_tickets():
    data_str, sha = get_file_content("tickets.json")
    tickets_list = json.loads(data_str)
    return tickets_list, sha

def save_feedback(feedback_list, sha):
    data_str = json.dumps(feedback_list, indent=2)
    return update_file_content("feedback.json", data_str, sha, "Update feedback data")

def save_tickets(tickets_list, sha):
    data_str = json.dumps(tickets_list, indent=2)
    return update_file_content("tickets.json", data_str, sha, "Update tickets data")

def remove_old_feedback(feedback_list):
    cutoff = datetime.utcnow() - timedelta(hours=24)
    filtered = [fb for fb in feedback_list if datetime.strptime(fb["created_at"], "%Y-%m-%dT%H:%M:%S") > cutoff]
    return filtered

# --- Initialize session state variables ---
if "tickets_sha" not in st.session_state:
    _, st.session_state["tickets_sha"] = load_tickets()
if "logged_in" not in st.session_state:
    st.session_state["logged_in"] = False
if "login_error" not in st.session_state:
    st.session_state["login_error"] = False

# --- Streamlit UI ---

st.set_page_config(page_title="AIKTC Anonymous Feedback", page_icon="📝", layout="wide")
st.title("📝 AIKTC Anonymous Feedback System")
st.markdown("Submit your feedback or queries anonymously. Your identity remains protected.")

# Load data
feedback_list, feedback_sha = load_feedback()
tickets_list, _ = load_tickets()

# Remove feedback older than 24 hours
new_feedback_list = remove_old_feedback(feedback_list)
if len(new_feedback_list) < len(feedback_list):
    save_feedback(new_feedback_list, feedback_sha)
    feedback_list = new_feedback_list

# --- Public Feedback Submission ---
st.header("Anonymous Feedback")
with st.form("feedback_form"):
    feedback_message = st.text_area("Write your feedback here:", "", height=100)
    submitted_feedback = st.form_submit_button("Submit Feedback")

if submitted_feedback:
    if feedback_message.strip():
        new_fb = {
            "id": (max([fb["id"] for fb in feedback_list]) + 1) if feedback_list else 1,
            "message": feedback_message.strip(),
            "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        }
        feedback_list.append(new_fb)
        if save_feedback(feedback_list, feedback_sha):
            st.success("✅ Feedback submitted successfully!")
        else:
            st.error("❌ Failed to save feedback.")
    else:
        st.error("❌ Please enter some feedback before submitting.")

# --- Public Feedback Display ---
st.header("View Submitted Feedback")
if feedback_list:
    for fb in sorted(feedback_list, key=lambda x: x["created_at"], reverse=True):
        with st.expander(f"Feedback #{fb['id']} (Submitted: {fb['created_at']} UTC)"):
            st.write(fb["message"])
else:
    st.write("No feedback submitted yet.")

# --- Public Ticket Submission ---
st.header("Submit a Ticket/Query")
with st.form("ticket_form"):
    ticket_query = st.text_area("Write your query here:", "", height=100)
    submitted_ticket = st.form_submit_button("Submit Ticket")

if submitted_ticket:
    if ticket_query.strip():
        new_id = (max([t["id"] for t in tickets_list]) + 1) if tickets_list else 1
        new_ticket = {
            "id": new_id,
            "query": ticket_query.strip(),
            "status": "In Process",
            "created_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
            "updated_at": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
        }
        tickets_list.append(new_ticket)
        if save_tickets(tickets_list, st.session_state["tickets_sha"]):
            st.success("✅ Ticket submitted successfully!")
            # Reload SHA after save
            _, new_sha = load_tickets()
            st.session_state["tickets_sha"] = new_sha
        else:
            st.error("❌ Failed to save ticket.")
    else:
        st.error("❌ Please enter a query before submitting.")

# --- Public Ticket Display ---
st.header("View Tickets")
if tickets_list:
    for ticket in sorted(tickets_list, key=lambda x: x["created_at"], reverse=True):
        if ticket["status"] != "Completed":
            with st.expander(f"Ticket #{ticket['id']} - {ticket['status']} (Created: {ticket['created_at']} UTC)"):
                st.write(f"**Query:** {ticket['query']}")
                st.write(f"Last Updated: {ticket['updated_at']} UTC")
else:
    st.write("No tickets submitted yet.")

# --- Sidebar Admin Login ---
st.sidebar.title("🔐 Admin Login")

if not st.session_state["logged_in"]:
    password = st.sidebar.text_input("Enter admin password:", type="password")
    if st.sidebar.button("Login"):
        if password == st.secrets["admin_password"]:
            st.session_state["logged_in"] = True
            st.session_state["login_error"] = False
            st.sidebar.success("Logged in successfully!")
            st.experimental_rerun()
        else:
            st.session_state["login_error"] = True
    if st.session_state["login_error"]:
        st.sidebar.error("❌ Incorrect password. Try again.")
else:
    st.sidebar.success("✅ Logged in as admin")
    if st.sidebar.button("Logout"):
        st.session_state["logged_in"] = False
        st.experimental_rerun()

# --- Admin Panel ---
if st.session_state["logged_in"]:
    st.markdown("---")
    st.header("🛠️ Admin Panel - Manage Feedback and Tickets")

    # Reload fresh data and SHAs for admin actions
    feedback_list, feedback_sha = load_feedback()
    tickets_list, tickets_sha = load_tickets()
    st.session_state["tickets_sha"] = tickets_sha

    # --- Feedback Management ---
    with st.container():
        st.subheader("Feedback Management")
        if feedback_list:
            for fb in sorted(feedback_list, key=lambda x: x["created_at"], reverse=True):
                with st.expander(f"Feedback #{fb['id']} (Submitted: {fb['created_at']} UTC)", expanded=False):
                    edited_message = st.text_area("Edit feedback message:", fb["message"], key=f"fb_edit_{fb['id']}")
                    col1, col2 = st.columns([1,1])
                    with col1:
                        if st.button("Save Feedback", key=f"fb_save_{fb['id']}"):
                            fb["message"] = edited_message.strip()
                            if save_feedback(feedback_list, feedback_sha):
                                st.success("✅ Feedback saved.")
                                st.experimental_rerun()
                            else:
                                st.error("❌ Failed to save feedback.")
                    with col2:
                        if st.button("Delete Feedback", key=f"fb_del_{fb['id']}"):
                            if st.confirm(f"Are you sure you want to delete feedback #{fb['id']}?"):
                                feedback_list = [f for f in feedback_list if f["id"] != fb["id"]]
                                if save_feedback(feedback_list, feedback_sha):
                                    st.success("✅ Feedback deleted.")
                                    st.experimental_rerun()
                                else:
                                    st.error("❌ Failed to delete feedback.")
        else:
            st.write("No feedback available.")

    st.markdown("---")

    # --- Ticket Management ---
    with st.container():
        st.subheader("Ticket Management")
        if tickets_list:
            for ticket in sorted(tickets_list, key=lambda x: x["created_at"], reverse=True):
                with st.expander(f"Ticket #{ticket['id']} - {ticket['status']} (Created: {ticket['created_at']} UTC)", expanded=False):
                    edited_query = st.text_area("Edit ticket query:", ticket["query"], key=f"tk_edit_{ticket['id']}")
                    new_status = st.selectbox("Update Status:", ["In Process", "Completed"], index=0 if ticket["status"]=="In Process" else 1, key=f"tk_status_{ticket['id']}")
                    col1, col2, col3 = st.columns([1,1,1])
                    with col1:
                        if st.button("Save Ticket", key=f"tk_save_{ticket['id']}"):
                            ticket["query"] = edited_query.strip()
                            ticket["status"] = new_status
                            ticket["updated_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
                            if save_tickets(tickets_list, tickets_sha):
                                st.success("✅ Ticket saved.")
                                st.experimental_rerun()
                            else:
                                st.error("❌ Failed to save ticket.")
                    with col2:
                        if st.button("Delete Ticket", key=f"tk_del_{ticket['id']}"):
                            if st.confirm(f"Are you sure you want to delete ticket #{ticket['id']}?"):
                                tickets_list = [t for t in tickets_list if t["id"] != ticket["id"]]
                                if save_tickets(tickets_list, tickets_sha):
                                    st.success("✅ Ticket deleted.")
                                    st.experimental_rerun()
                                else:
                                    st.error("❌ Failed to delete ticket.")
                    with col3:
                        if new_status == "Completed":
                            if st.button("Mark Completed & Remove", key=f"tk_comp_{ticket['id']}"):
                                tickets_list = [t for t in tickets_list if t["id"] != ticket["id"]]
                                if save_tickets(tickets_list, tickets_sha):
                                    st.success("✅ Ticket marked completed and removed from public view.")
                                    st.experimental_rerun()
                                else:
                                    st.error("❌ Failed to update ticket.")
        else:
            st.write("No tickets available.")

st.markdown("---")
st.markdown("*This platform is for anonymous submissions to improve AIKTC College. All data is handled securely.*")
