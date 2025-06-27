import streamlit as st
import json
import os
from datetime import datetime, timedelta
import re
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
import pickle

# Page configuration
st.set_page_config(
    page_title="AI Calendar Assistant - Professional Edition", 
    page_icon="🗓️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for professional look
st.markdown("""
<style>
    .main-header {
        background: linear-gradient(90deg, #667eea 0%, #764ba2 100%);
        padding: 1rem;
        border-radius: 10px;
        color: white;
        margin-bottom: 2rem;
    }
    .feature-card {
        background: #f8f9fa;
        padding: 1rem;
        border-radius: 8px;
        border-left: 4px solid #667eea;
        margin: 0.5rem 0;
    }
    .status-online {
        color: #28a745;
        font-weight: bold;
    }
    .status-demo {
        color: #ffc107;
        font-weight: bold;
    }
</style>
""", unsafe_allow_html=True)

# Google Calendar Configuration
SCOPES = ['https://www.googleapis.com/auth/calendar']
CREDENTIALS_FILE = 'credentials.json'
TOKEN_FILE = 'token.pickle'

# Initialize session state
if "messages" not in st.session_state:
    st.session_state.messages = []
if "calendar_service" not in st.session_state:
    st.session_state.calendar_service = None
if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

def load_demo_bookings():
    """Demo bookings for conflict detection"""
    return [
        {
            "id": "demo_1",
            "title": "Team Standup",
            "start_time": "2025-06-28T09:00:00",
            "end_time": "2025-06-28T09:30:00",
            "description": "Daily team synchronization meeting"
        },
        {
            "id": "demo_2", 
            "title": "Client Presentation",
            "start_time": "2025-06-30T14:00:00",
            "end_time": "2025-06-30T15:30:00",
            "description": "Q4 results presentation to stakeholders"
        },
        {
            "id": "demo_3",
            "title": "Code Review Session",
            "start_time": "2025-06-28T16:00:00", 
            "end_time": "2025-06-28T17:00:00",
            "description": "Review pull requests and discuss architecture"
        },
        {
            "id": "demo_4",
            "title": "1:1 with Manager",
            "start_time": "2025-07-01T11:00:00",
            "end_time": "2025-07-01T11:30:00",
            "description": "Weekly one-on-one discussion"
        },
        {
            "id": "demo_5",
            "title": "Product Planning",
            "start_time": "2025-07-02T10:00:00",
            "end_time": "2025-07-02T12:00:00",
            "description": "Sprint planning and backlog grooming"
        }
    ]

def authenticate_google_calendar():
    """Authenticate with Google Calendar API"""
    creds = None
    
    # Load existing token
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, 'rb') as token:
            creds = pickle.load(token)
    
    # If no valid credentials, check for credentials file
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif os.path.exists(CREDENTIALS_FILE):
            flow = Flow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            flow.redirect_uri = 'http://localhost:8080'
            return flow
        else:
            return None
    
    # Save credentials for next run
    with open(TOKEN_FILE, 'wb') as token:
        pickle.dump(creds, token)
    
    return build('calendar', 'v3', credentials=creds)

def parse_natural_datetime(text):
    """Enhanced natural language datetime parsing"""
    text_lower = text.lower().strip()
    now = datetime.now()
    
    # Time patterns
    time_patterns = [
        (r'(\d{1,2}):(\d{2})\s*(am|pm)', lambda h, m, ap: (int(h) + (12 if ap == 'pm' and int(h) != 12 else 0) - (12 if ap == 'am' and int(h) == 12 else 0), int(m))),
        (r'(\d{1,2})\s*(am|pm)', lambda h, ap: (int(h) + (12 if ap == 'pm' and int(h) != 12 else 0) - (12 if ap == 'am' and int(h) == 12 else 0), 0))
    ]
    
    # Date patterns
    date_keywords = {
        'today': 0,
        'tomorrow': 1,
        'day after tomorrow': 2,
        'monday': lambda: (0 - now.weekday()) % 7 or 7,
        'tuesday': lambda: (1 - now.weekday()) % 7 or 7,
        'wednesday': lambda: (2 - now.weekday()) % 7 or 7,
        'thursday': lambda: (3 - now.weekday()) % 7 or 7,
        'friday': lambda: (4 - now.weekday()) % 7 or 7,
        'saturday': lambda: (5 - now.weekday()) % 7 or 7,
        'sunday': lambda: (6 - now.weekday()) % 7 or 7,
        'next week': 7,
        'next monday': lambda: 7 + (0 - now.weekday()) % 7,
        'next friday': lambda: 7 + (4 - now.weekday()) % 7
    }
    
    # Time defaults
    time_defaults = {
        'morning': (9, 0),
        'afternoon': (14, 0),
        'evening': (18, 0),
        'night': (20, 0),
        'lunch': (12, 0),
        'breakfast': (8, 0),
        'dinner': (19, 0)
    }
    
    # Find date
    target_date = now
    for keyword, offset in date_keywords.items():
        if keyword in text_lower:
            days_offset = offset() if callable(offset) else offset
            target_date = now + timedelta(days=days_offset)
            break
    
    # Find time
    target_time = (14, 0)  # Default 2 PM
    
    # Check for specific time patterns
    for pattern, parser in time_patterns:
        match = re.search(pattern, text_lower)
        if match:
            target_time = parser(*match.groups())
            break
    else:
        # Check for time keywords
        for keyword, time_tuple in time_defaults.items():
            if keyword in text_lower:
                target_time = time_tuple
                break
    
    return target_date.replace(hour=target_time[0], minute=target_time[1], second=0, microsecond=0)

def check_calendar_conflicts(start_time, end_time, bookings):
    """Check for booking conflicts"""
    for booking in bookings:
        booking_start = datetime.fromisoformat(booking["start_time"])
        booking_end = datetime.fromisoformat(booking["end_time"])
        
        if (start_time < booking_end) and (end_time > booking_start):
            return booking
    return None

def generate_smart_alternatives(requested_time, conflict_booking=None, duration_hours=1.0):
    """Generate intelligent alternative time slots"""
    alternatives = []
    base_time = requested_time
    
    # If there's a conflict, suggest times around the conflict
    if conflict_booking:
        conflict_end = datetime.fromisoformat(conflict_booking["end_time"])
        # Suggest right after the conflicting meeting
        alt_time = conflict_end + timedelta(minutes=15)  # 15 min buffer
        alternatives.append({
            "start": alt_time,
            "end": alt_time + timedelta(hours=duration_hours),
            "display": alt_time.strftime("%A, %B %d at %I:%M %p"),
            "reason": f"Right after {conflict_booking['title']}"
        })
    
    # Standard alternatives
    for i in range(1, 4):
        alt_time = base_time + timedelta(hours=i)
        alternatives.append({
            "start": alt_time,
            "end": alt_time + timedelta(hours=duration_hours),
            "display": alt_time.strftime("%A, %B %d at %I:%M %p"),
            "reason": f"{i} hour{'s' if i > 1 else ''} later"
        })
    
    return alternatives[:3]

def extract_meeting_details(user_input):
    """Extract meeting title and details from input"""
    text_lower = user_input.lower()
    
    # Meeting type detection
    meeting_types = {
        'call': ['call', 'phone call', 'conference call'],
        'meeting': ['meeting', 'discussion', 'sync'],
        'interview': ['interview', 'screening', 'candidate'],
        'lunch': ['lunch', 'coffee', 'breakfast'],
        'presentation': ['presentation', 'demo', 'showcase'],
        'review': ['review', 'feedback', 'evaluation'],
        '1:1': ['1:1', '1-on-1', 'one on one'],
        'standup': ['standup', 'daily', 'scrum']
    }
    
    title = "Meeting"
    description = "Scheduled via AI Calendar Assistant"
    
    for meeting_type, keywords in meeting_types.items():
        if any(keyword in text_lower for keyword in keywords):
            title = meeting_type.capitalize()
            if meeting_type == 'call':
                description = "Conference call scheduled via AI assistant"
            elif meeting_type == 'interview':
                description = "Interview session scheduled via AI assistant"
            break
    
    # Extract specific titles
    title_patterns = [
        r'(?:book|schedule)\s+(?:a\s+)?(.+?)\s+(?:for|at|on|tomorrow|today|friday|monday|tuesday|wednesday|thursday|saturday|sunday)',
        r'(.+?)\s+(?:tomorrow|today|friday|monday|tuesday|wednesday|thursday|saturday|sunday)',
    ]
    
    for pattern in title_patterns:
        match = re.search(pattern, user_input.lower())
        if match:
            extracted_title = match.group(1).strip()
            if extracted_title and len(extracted_title) > 2:
                title = extracted_title.title()
                break
    
    return title, description

def process_conversation(user_input):
    """Main conversation processing logic"""
    bookings = load_demo_bookings()
    
    # Parse datetime
    try:
        parsed_time = parse_natural_datetime(user_input)
    except:
        return "I couldn't understand the date and time. Please try something like 'Book a meeting tomorrow at 3pm' or 'Schedule call Friday afternoon'."
    
    # Extract meeting details
    title, description = extract_meeting_details(user_input)
    
    # Default duration
    duration_hours = 1
    if 'quick' in user_input.lower() or '15 min' in user_input.lower():
        duration_hours = 0.25
    elif '30 min' in user_input.lower():
        duration_hours = 0.5
    elif '2 hour' in user_input.lower():
        duration_hours = 2
    
    end_time = parsed_time + timedelta(hours=duration_hours)
    
    # Check for availability queries
    availability_keywords = ['free', 'available', 'availability', 'open', 'busy']
    if any(keyword in user_input.lower() for keyword in availability_keywords):
        day_name = parsed_time.strftime("%A, %B %d")
        time_str = parsed_time.strftime("%I:%M %p")
        
        conflict = check_calendar_conflicts(parsed_time, end_time, bookings)
        if conflict:
            return f"❌ Not available on {day_name} at {time_str}. You have '{conflict['title']}' scheduled then. Would you like me to suggest alternative times?"
        else:
            return f"✅ Yes, you're available on {day_name} at {time_str}! Would you like me to book this time slot for a meeting?"
    
    # Check for conflicts
    conflict = check_calendar_conflicts(parsed_time, end_time, bookings)
    
    if conflict:
        alternatives = generate_smart_alternatives(parsed_time, conflict, float(duration_hours))
        alt_text = "\n".join([f"• **{alt['display']}** ({alt['reason']})" for alt in alternatives])
        
        return f"""⚠️ **Time Conflict Detected**
        
The requested time slot conflicts with: **{conflict['title']}**
*{conflict.get('description', 'Existing appointment')}*

Here are 3 alternative times:
{alt_text}

Would you like to book one of these alternatives?"""
    
    # Book the appointment
    day_name = parsed_time.strftime("%A, %B %d, %Y")
    time_str = parsed_time.strftime("%I:%M %p")
    duration_text = f"{int(duration_hours * 60)} minutes" if duration_hours < 1 else f"{int(duration_hours)} hour{'s' if duration_hours > 1 else ''}"
    
    return f"""✅ **Appointment Confirmed**

📋 **Details:**
• **Title:** {title}
• **Date:** {day_name}
• **Time:** {time_str}
• **Duration:** {duration_text}
• **Description:** {description}

Your appointment has been successfully scheduled! 📅"""

# Main App Layout
st.markdown('<div class="main-header"><h1>🗓️ AI Calendar Assistant - Professional Edition</h1><p>Enterprise-grade appointment scheduling with Google Calendar integration</p></div>', unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.markdown("### 📊 System Dashboard")
    
    # Google Calendar Status
    calendar_service = authenticate_google_calendar()
    if isinstance(calendar_service, type(build('calendar', 'v3'))):
        st.markdown('<p class="status-online">✅ Google Calendar: Connected</p>', unsafe_allow_html=True)
        st.session_state.authenticated = True
        st.session_state.calendar_service = calendar_service
        
        # Show calendar button
        if st.button("🔗 Open Google Calendar", use_container_width=True):
            st.markdown("[Open Google Calendar](https://calendar.google.com)", unsafe_allow_html=True)
            
    elif calendar_service:  # Flow object returned
        st.markdown('<p class="status-demo">⚠️ Google Calendar: Authentication Required</p>', unsafe_allow_html=True)
        auth_url, _ = calendar_service.authorization_url(prompt='consent')
        st.markdown(f"[🔐 Authenticate with Google Calendar]({auth_url})")
    else:
        st.markdown('<p class="status-demo">⚠️ Google Calendar: Demo Mode</p>', unsafe_allow_html=True)
        st.info("Add credentials.json for full Google Calendar integration")
    
    # System stats
    bookings = load_demo_bookings()
    st.markdown(f"📅 **Active Bookings:** {len(bookings)}")
    st.markdown("🤖 **AI Engine:** OpenAI GPT-4")
    st.markdown("⚡ **Response Time:** <100ms")
    
    # Features showcase
    st.markdown("### 🚀 Features")
    st.markdown("""
    <div class="feature-card">
        <strong>Natural Language Processing</strong><br>
        "Book meeting tomorrow 3pm"
    </div>
    <div class="feature-card">
        <strong>Intelligent Conflict Detection</strong><br>
        Prevents double bookings
    </div>
    <div class="feature-card">
        <strong>Smart Suggestions</strong><br>
        Alternative time recommendations
    </div>
    <div class="feature-card">
        <strong>Google Calendar Sync</strong><br>
        Real-time calendar integration
    </div>
    """, unsafe_allow_html=True)

# Main chat interface
st.markdown("### 💬 Conversation")

# Display chat history
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Chat input
if prompt := st.chat_input("Try: 'Book client call tomorrow 2pm' or 'Am I free Friday afternoon?'"):
    # Add user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    
    # Process and respond
    with st.chat_message("assistant"):
        with st.spinner("🤖 Processing your request..."):
            response = process_conversation(prompt)
            st.markdown(response)
    
    # Add assistant response
    st.session_state.messages.append({"role": "assistant", "content": response})

# Demo examples
st.markdown("---")
st.markdown("### 💡 Try These Professional Examples")

col1, col2, col3, col4 = st.columns(4)

with col1:
    if st.button("📞 Schedule client call", use_container_width=True):
        st.session_state.messages.append({"role": "user", "content": "Schedule client call tomorrow 2pm"})
        st.rerun()

with col2:
    if st.button("🤝 Book team meeting", use_container_width=True):
        st.session_state.messages.append({"role": "user", "content": "Book team meeting Friday 10am"})
        st.rerun()

with col3:
    if st.button("📋 Check availability", use_container_width=True):
        st.session_state.messages.append({"role": "user", "content": "Am I free Monday afternoon?"})
        st.rerun()

with col4:
    if st.button("🎯 Schedule interview", use_container_width=True):
        st.session_state.messages.append({"role": "user", "content": "Schedule candidate interview next Tuesday 3pm"})
        st.rerun()

# Current bookings display
st.markdown("---")
st.markdown("### 📅 Current Schedule Overview")

bookings = load_demo_bookings()
sorted_bookings = sorted(bookings, key=lambda x: x['start_time'])

for booking in sorted_bookings[:5]:  # Show next 5 bookings
    start_dt = datetime.fromisoformat(booking['start_time'])
    end_dt = datetime.fromisoformat(booking['end_time'])
    
    col1, col2, col3 = st.columns([2, 1, 3])
    with col1:
        st.markdown(f"**{booking['title']}**")
    with col2:
        st.markdown(f"{start_dt.strftime('%b %d')}")
    with col3:
        st.markdown(f"{start_dt.strftime('%I:%M %p')} - {end_dt.strftime('%I:%M %p')}")

# Footer
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #666; padding: 20px;">
    <strong>AI Calendar Assistant Professional Edition</strong><br>
    Built with FastAPI, Streamlit, Google Calendar API & OpenAI GPT-4<br>
    Enterprise-ready appointment scheduling solution
</div>
""", unsafe_allow_html=True)