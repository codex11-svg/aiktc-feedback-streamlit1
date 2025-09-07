import streamlit as st
import requests
import base64
import json
from datetime import datetime, timedelta

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

st.set_page_config(page_title="AIKTC Anonymous Feedback", page_icon="📝", layout="wide")
st.title("📝 AIKTC Anonymous Feedback System")
st.markdown("Submit your feedback or queries anonymously. Your identity remains protected.")

feedback_list, feedback_sha = load_feedback()
tickets_list, tickets_sha = load_tickets()

new_feedback_list = remove_old_feedback(feedback_list)
if len(new_feedback_list) < len(feedback_list):
    save_feedback(new_feedback_list, feedback_sha)
    feedback_list = new_feedback_list

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
            feedback_sha = None
        else:
            st.error("❌ Failed to save feedback.")
    else:
        st.error("❌ Please enter some feedback before submitting.")

st.header("View Submitted Feedback")
if feedback_list:
    for fb in sorted(feedback_list, key=lambda x: x["created_at"], reverse=True):
        with st.expander(f"Feedback #{fb['id']} (Submitted: {fb['created_at']} UTC)"):
            st.write(fb["message"])
else:
    st.write("No feedback submitted yet.")

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
        if save_tickets(tickets_list, tickets_sha):
            st.success("✅ Ticket submitted successfully!")
            tickets_sha = None
        else:
            st.error("❌ Failed to save ticket.")
    else:
        st.error("❌ Please enter a query before submitting.")

st.header("View and Update Tickets")
if tickets_list:
    for ticket in sorted(tickets_list, key=lambda x: x["created_at"], reverse=True):
        with st.expander(f"Ticket #{ticket['id']} - {ticket['status']} (Created: {ticket['created_at']} UTC)"):
            st.write(f"**Query:** {ticket['query']}")
            st.write(f"Last Updated: {ticket['updated_at']} UTC")
            if ticket["status"] != "Completed":
                new_status = st.selectbox("Update Status:", ["In Process", "Completed"], index=0, key=f"status_{ticket['id']}")
                if st.button("Update", key=f"update_{ticket['id']}"):
                    ticket["status"] = new_status
                    ticket["updated_at"] = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
                    if save_tickets(tickets_list, tickets_sha):
                        st.success("✅ Status updated!")
                        tickets_sha = None
                        st.experimental_rerun()
                    else:
                        st.error("❌ Failed to update ticket.")
else:
    st.write("No tickets submitted yet.")

st.markdown("---")
st.markdown("*This platform is for anonymous submissions to improve AIKTC College. All data is handled securely.*")