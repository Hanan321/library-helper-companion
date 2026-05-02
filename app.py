import streamlit as st

st.set_page_config(
    page_title="Library Helper Companion",
    page_icon="📚",
    layout="centered"
)

# ---------- Basic Styling ----------
st.markdown("""
<style>
.main-title {
    font-size: 36px;
    font-weight: bold;
    text-align: center;
}
.subtitle {
    font-size: 20px;
    text-align: center;
    color: #555;
}
.task-card {
    padding: 20px;
    border-radius: 15px;
    background-color: #f7f7f7;
    margin-bottom: 15px;
}
.big-step {
    font-size: 24px;
    font-weight: bold;
}
.help-box {
    background-color: #fff3cd;
    padding: 15px;
    border-radius: 10px;
    font-size: 18px;
}
</style>
""", unsafe_allow_html=True)

# ---------- App Title ----------
st.markdown('<div class="main-title">📚 Library Helper Companion</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="subtitle">A simple step-by-step helper for library tasks</div>',
    unsafe_allow_html=True
)

st.divider()

# ---------- Task Data ----------
tasks = {
    "Check In Returned Books": [
        "Pick up one returned book at a time.",
        "Scan the book barcode in the library system.",
        "Check that the system says the book was checked in.",
        "Look for any hold or warning message.",
        "If there is no hold, place the book on the shelving cart.",
        "If there is a hold, place the book on the hold shelf or ask a supervisor.",
        "Repeat with the next returned book."
    ],
    "Shelve Books": [
        "Look at the call number or shelf label on the book.",
        "Go to the correct shelf section.",
        "Compare the book label with nearby books.",
        "Place the book in the correct order.",
        "If you are unsure, place it on the review cart or ask for help."
    ],
    "Help a Patron Find a Book": [
        "Ask the patron for the title, author, or topic.",
        "Search the library catalog.",
        "Check if the book is available.",
        "Write down or show the shelf location.",
        "If needed, walk with the patron to the correct area.",
        "If the book is unavailable, offer to place a hold or ask a supervisor."
    ],
    "Process Holds": [
        "Open the holds list or check the hold notification.",
        "Find the item that needs to be held.",
        "Print or write the hold slip if needed.",
        "Place the hold slip with the item.",
        "Put the item on the correct hold shelf.",
        "Double-check the patron name or hold number."
    ],
    "Closing Checklist": [
        "Check the return area for remaining books.",
        "Make sure books are on the correct carts.",
        "Log out of the library system.",
        "Clean the desk area.",
        "Check for personal items.",
        "Tell the supervisor if anything unusual happened."
    ]
}

# ---------- Session State ----------
if "selected_task" not in st.session_state:
    st.session_state.selected_task = None

if "step_index" not in st.session_state:
    st.session_state.step_index = 0

# ---------- Sidebar ----------
st.sidebar.header("Settings")
support_name = st.sidebar.text_input("Support person name", value="Supervisor")
support_phone = st.sidebar.text_input("Support phone or note", value="Ask the front desk supervisor for help.")

st.sidebar.info(
    "This app is a task helper, not a medical tool. "
    "A supervisor or trusted person should review the checklists."
)

# ---------- Task Selection ----------
st.subheader("Choose a task")

for task_name in tasks:
    if st.button(task_name, use_container_width=True):
        st.session_state.selected_task = task_name
        st.session_state.step_index = 0

st.divider()

# ---------- Task Step Mode ----------
if st.session_state.selected_task:
    task_name = st.session_state.selected_task
    steps = tasks[task_name]
    current_step = st.session_state.step_index

    st.subheader(f"Current Task: {task_name}")

    st.progress((current_step + 1) / len(steps))

    st.markdown(
        f"""
        <div class="task-card">
            <div class="big-step">Step {current_step + 1} of {len(steps)}</div>
            <p style="font-size:22px;">{steps[current_step]}</p>
        </div>
        """,
        unsafe_allow_html=True
    )

    col1, col2 = st.columns(2)

    with col1:
        if st.button("⬅️ Previous Step", use_container_width=True):
            if st.session_state.step_index > 0:
                st.session_state.step_index -= 1
                st.rerun()

    with col2:
        if st.button("Next Step ➡️", use_container_width=True):
            if st.session_state.step_index < len(steps) - 1:
                st.session_state.step_index += 1
                st.rerun()
            else:
                st.success("Task completed. Great job!")

    st.divider()

    if st.button("❓ I Need Help", use_container_width=True):
        st.markdown(
            f"""
            <div class="help-box">
                <b>Ask for help:</b><br>
                Contact: {support_name}<br>
                Note: {support_phone}
            </div>
            """,
            unsafe_allow_html=True
        )

else:
    st.info("Choose a task above to begin.")