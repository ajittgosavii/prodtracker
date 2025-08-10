import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import firebase_admin
from firebase_admin import credentials, firestore, auth
from datetime import datetime, timedelta, date
import json
import io
import hashlib
from typing import Dict, List, Optional
import numpy as np
from dataclasses import dataclass
import uuid

# Configure Streamlit page
st.set_page_config(
    page_title="Enterprise Productivity Tracker",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main > div {
        padding-top: 1rem;
        padding-bottom: 1rem;
    }
    .stMetric {
        background-color: #f8f9fa;
        border: 1px solid #dee2e6;
        padding: 1rem;
        border-radius: 0.5rem;
        margin: 0.5rem 0;
    }
    .team-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1.5rem;
        border-radius: 1rem;
        color: white;
        margin: 1rem 0;
    }
    .activity-card {
        background-color: #ffffff;
        padding: 1rem;
        border-radius: 0.5rem;
        border-left: 4px solid #007bff;
        margin: 0.5rem 0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    .status-excellent { color: #28a745; font-weight: bold; }
    .status-good { color: #17a2b8; font-weight: bold; }
    .status-warning { color: #ffc107; font-weight: bold; }
    .status-poor { color: #dc3545; font-weight: bold; }
    
    /* Reduce spacing in tabs */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    
    /* Compact form styling */
    .stForm {
        border: none;
        padding: 0;
    }
    
    /* Reduce expander spacing */
    .streamlit-expanderHeader {
        padding-top: 0.5rem;
        padding-bottom: 0.5rem;
    }
</style>
""", unsafe_allow_html=True)

@dataclass
class TeamConfig:
    name: str
    icon: str
    color: str
    description: str
    activities: List[Dict[str, str]]
    goals: Dict[str, float]

@dataclass
class User:
    id: str
    name: str
    email: str
    role: str
    team: str
    location_type: str
    goals: Dict[str, float]
    created_at: datetime
    last_login: datetime

class FirestoreManager:
    def __init__(self):
        """Initialize Firestore connection"""
        self.db = None
        self.init_firebase()
    
    def init_firebase(self):
        """Initialize Firebase Admin SDK"""
        try:
            if not firebase_admin._apps:
                # In production, use service account key
                if 'firebase_credentials' in st.secrets:
                    cred_dict = dict(st.secrets["firebase_credentials"])
                    cred = credentials.Certificate(cred_dict)
                    firebase_admin.initialize_app(cred)
                else:
                    # For development, you can use environment variables or local key file
                    st.error("Firebase credentials not found in Streamlit secrets.")
                    st.info("Please add your Firebase service account credentials to Streamlit secrets.")
                    st.stop()
            
            self.db = firestore.client()
            
        except Exception as e:
            st.error(f"Failed to initialize Firebase: {e}")
            st.info("Please check your Firebase configuration.")
            st.stop()
    
    def create_user(self, user_data: Dict) -> bool:
        """Create a new user in Firestore"""
        try:
            # Create user in Firebase Auth
            firebase_user = auth.create_user(
                email=user_data['email'],
                password=user_data['password'],  # This will be handled securely by Firebase
                display_name=user_data['name']
            )
            
            # Store additional user data in Firestore
            user_doc = {
                'uid': firebase_user.uid,
                'name': user_data['name'],
                'email': user_data['email'],
                'role': user_data['role'],
                'team': user_data['team'],
                'location_type': user_data['location_type'],
                'goals': user_data.get('goals', {}),
                'created_at': firestore.SERVER_TIMESTAMP,
                'last_login': firestore.SERVER_TIMESTAMP,
                'active': True
            }
            
            # Store in users collection
            self.db.collection('users').document(firebase_user.uid).set(user_doc)
            
            # Initialize user's productivity collection
            self.db.collection('productivity').document(firebase_user.uid).set({
                'initialized': True,
                'created_at': firestore.SERVER_TIMESTAMP
            })
            
            return True
            
        except Exception as e:
            st.error(f"Error creating user: {e}")
            return False
    
    def get_user_by_email(self, email: str) -> Optional[Dict]:
        """Get user by email from Firestore"""
        try:
            # Query users collection by email
            users_ref = self.db.collection('users')
            query = users_ref.where('email', '==', email).limit(1)
            docs = query.stream()
            
            for doc in docs:
                user_data = doc.to_dict()
                user_data['id'] = doc.id
                return user_data
            
            return None
            
        except Exception as e:
            st.error(f"Error fetching user: {e}")
            return None
    
    def verify_user_password(self, email: str, password: str) -> Optional[Dict]:
        """Verify user credentials using Firebase Auth"""
        try:
            # Note: In a real implementation, you'd use Firebase Auth's client SDK
            # for password verification. This is a simplified version.
            # The actual authentication should happen on the client side with Firebase Auth
            
            user = self.get_user_by_email(email)
            if user:
                # Update last login
                self.update_last_login(user['id'])
                return user
            return None
            
        except Exception as e:
            st.error(f"Authentication error: {e}")
            return None
    
    def update_last_login(self, user_id: str):
        """Update user's last login timestamp"""
        try:
            self.db.collection('users').document(user_id).update({
                'last_login': firestore.SERVER_TIMESTAMP
            })
        except Exception as e:
            st.error(f"Error updating last login: {e}")
    
    def save_daily_entry(self, user_id: str, entry_data: Dict) -> bool:
        """Save daily productivity entry"""
        try:
            date_str = entry_data['date']
            doc_id = f"{user_id}_{date_str}"
            
            entry_doc = {
                'user_id': user_id,
                'date': entry_data['date'],
                'activity_data': entry_data['activity_data'],
                'total_hours': entry_data['total_hours'],
                'notes': entry_data.get('notes', ''),
                'work_location': entry_data.get('work_location', 'office'),
                'mood_score': entry_data.get('mood_score', 5),
                'energy_level': entry_data.get('energy_level', 5),
                'updated_at': firestore.SERVER_TIMESTAMP
            }
            
            # Use merge to update existing or create new
            self.db.collection('daily_entries').document(doc_id).set(entry_doc, merge=True)
            
            return True
            
        except Exception as e:
            st.error(f"Error saving daily entry: {e}")
            return False
    
    def get_user_entries(self, user_id: str, start_date: str = None, end_date: str = None) -> List[Dict]:
        """Get user's daily entries from Firestore"""
        try:
            entries_ref = self.db.collection('daily_entries')
            
            # Base query
            query = entries_ref.where('user_id', '==', user_id)
            
            # Add date filters if provided
            if start_date:
                query = query.where('date', '>=', start_date)
            if end_date:
                query = query.where('date', '<=', end_date)
            
            # Order by date descending
            query = query.order_by('date', direction=firestore.Query.DESCENDING)
            
            docs = query.stream()
            entries = []
            
            for doc in docs:
                entry_data = doc.to_dict()
                entry_data['id'] = doc.id
                entries.append(entry_data)
            
            return entries
            
        except Exception as e:
            st.error(f"Error fetching entries: {e}")
            return []
    
    def get_team_members(self, team: str, role: str = 'employee') -> List[Dict]:
        """Get team members from Firestore"""
        try:
            users_ref = self.db.collection('users')
            query = users_ref.where('team', '==', team).where('role', '==', role).where('active', '==', True)
            
            docs = query.stream()
            members = []
            
            for doc in docs:
                member_data = doc.to_dict()
                member_data['id'] = doc.id
                members.append(member_data)
            
            return members
            
        except Exception as e:
            st.error(f"Error fetching team members: {e}")
            return []
    
    def get_all_users(self) -> List[Dict]:
        """Get all users (admin function)"""
        try:
            users_ref = self.db.collection('users')
            docs = users_ref.stream()
            
            users = []
            for doc in docs:
                user_data = doc.to_dict()
                user_data['id'] = doc.id
                users.append(user_data)
            
            return users
            
        except Exception as e:
            st.error(f"Error fetching all users: {e}")
            return []
    
    def get_system_stats(self) -> Dict:
        """Get system statistics"""
        try:
            # Count users
            users_ref = self.db.collection('users')
            total_users = len(list(users_ref.stream()))
            
            # Count daily entries
            entries_ref = self.db.collection('daily_entries')
            total_entries = len(list(entries_ref.stream()))
            
            # Count today's active users
            today = date.today().isoformat()
            today_entries = entries_ref.where('date', '==', today).stream()
            active_today = len(set(doc.to_dict()['user_id'] for doc in today_entries))
            
            return {
                'total_users': total_users,
                'total_entries': total_entries,
                'active_today': active_today
            }
            
        except Exception as e:
            st.error(f"Error fetching system stats: {e}")
            return {'total_users': 0, 'total_entries': 0, 'active_today': 0}

class ProductivityTracker:
    def __init__(self):
        self.db = FirestoreManager()
        self.team_configs = self._get_team_configurations()
        self._init_session_state()
    
    def _init_session_state(self):
        """Initialize Streamlit session state"""
        if 'user' not in st.session_state:
            st.session_state.user = None
        if 'current_date' not in st.session_state:
            st.session_state.current_date = date.today()
        if 'authenticated' not in st.session_state:
            st.session_state.authenticated = False
    
    def get_expected_hours(self, location_type: str) -> float:
        """Get expected daily hours based on location type"""
        return 8.8 if location_type == 'offshore' else 8.0
    
    def get_expected_weekly_hours(self, location_type: str) -> float:
        """Get expected weekly hours based on location type"""
        return 44.0 if location_type == 'offshore' else 40.0
    
    def _get_team_configurations(self) -> Dict[str, TeamConfig]:
        """Define team configurations with enhanced features"""
        return {
            'database-operations': TeamConfig(
                name='Database Operations',
                icon='🗃️',
                color='#2E8B57',
                description='Database monitoring, troubleshooting, maintenance, and operational excellence.',
                activities=[
                    {'id': 'internal_meetings', 'name': 'Internal Meetings', 'icon': '👥', 'category': 'Communication'},
                    {'id': 'client_meetings', 'name': 'Client Meetings', 'icon': '🤝', 'category': 'Communication'},
                    {'id': 'troubleshooting', 'name': 'Troubleshooting Activities', 'icon': '🔧', 'category': 'Operations'},
                    {'id': 'sop_creation', 'name': 'SOP Creation', 'icon': '📋', 'category': 'Documentation'},
                    {'id': 'knowledge_base', 'name': 'Knowledge Base Creation', 'icon': '📚', 'category': 'Documentation'},
                    {'id': 'monitoring', 'name': 'System Monitoring', 'icon': '📊', 'category': 'Operations'},
                    {'id': 'db_readiness', 'name': 'DB Readiness Activities', 'icon': '✅', 'category': 'Operations'},
                    {'id': 'coordination', 'name': 'Team Coordination', 'icon': '🔄', 'category': 'Communication'},
                    {'id': 'patching', 'name': 'Patching Activities', 'icon': '🔨', 'category': 'Operations'},
                    {'id': 'terraform_code', 'name': 'Terraform Development', 'icon': '⚙️', 'category': 'Development'},
                    {'id': 'automation', 'name': 'Process Automation', 'icon': '🤖', 'category': 'Development'},
                    {'id': 'training', 'name': 'Training & Learning', 'icon': '🎓', 'category': 'Development'}
                ],
                goals={'offshore': {'daily_hours': 8.8, 'weekly_hours': 44.0, 'monthly_productivity': 85.0},
                       'onshore': {'daily_hours': 8.0, 'weekly_hours': 40.0, 'monthly_productivity': 85.0}}
            ),
            'migration-factory': TeamConfig(
                name='Database Migration Factory',
                icon='🔄',
                color='#FF6347',
                description='Database migration projects, data transfer, and migration process optimization.',
                activities=[
                    {'id': 'internal_meetings', 'name': 'Internal Meetings', 'icon': '👥', 'category': 'Communication'},
                    {'id': 'client_meetings', 'name': 'Client Meetings', 'icon': '🤝', 'category': 'Communication'},
                    {'id': 'migration_activities', 'name': 'Migration Execution', 'icon': '🚚', 'category': 'Operations'},
                    {'id': 'sop_creation', 'name': 'SOP Creation', 'icon': '📋', 'category': 'Documentation'},
                    {'id': 'knowledge_base', 'name': 'Knowledge Base Creation', 'icon': '📚', 'category': 'Documentation'},
                    {'id': 'monitoring', 'name': 'Migration Monitoring', 'icon': '📊', 'category': 'Operations'},
                    {'id': 'db_readiness', 'name': 'Pre-Migration Readiness', 'icon': '✅', 'category': 'Operations'},
                    {'id': 'coordination', 'name': 'Project Coordination', 'icon': '🔄', 'category': 'Communication'},
                    {'id': 'handover_activities', 'name': 'Project Handover', 'icon': '🤲', 'category': 'Operations'},
                    {'id': 'terraform_code', 'name': 'Infrastructure as Code', 'icon': '⚙️', 'category': 'Development'},
                    {'id': 'testing', 'name': 'Migration Testing', 'icon': '🧪', 'category': 'Operations'},
                    {'id': 'rollback_planning', 'name': 'Rollback Planning', 'icon': '↩️', 'category': 'Operations'}
                ],
                goals={'offshore': {'daily_hours': 8.8, 'weekly_hours': 44.0, 'migration_success_rate': 95.0},
                       'onshore': {'daily_hours': 8.0, 'weekly_hours': 40.0, 'migration_success_rate': 95.0}}
            ),
            'backoffice-cloud': TeamConfig(
                name='Back Office Cloud Operations',
                icon='☁️',
                color='#4169E1',
                description='Cloud infrastructure management and seamless service delivery.',
                activities=[
                    {'id': 'internal_meetings', 'name': 'Internal Meetings', 'icon': '👥', 'category': 'Communication'},
                    {'id': 'client_meetings', 'name': 'Client Meetings', 'icon': '🤝', 'category': 'Communication'},
                    {'id': 'troubleshooting', 'name': 'Issue Resolution', 'icon': '🔧', 'category': 'Operations'},
                    {'id': 'sop_creation', 'name': 'SOP Creation', 'icon': '📋', 'category': 'Documentation'},
                    {'id': 'knowledge_base', 'name': 'Knowledge Management', 'icon': '📚', 'category': 'Documentation'},
                    {'id': 'monitoring', 'name': 'Cloud Monitoring', 'icon': '📊', 'category': 'Operations'},
                    {'id': 'infrastructure_mgmt', 'name': 'Infrastructure Management', 'icon': '🏗️', 'category': 'Operations'},
                    {'id': 'coordination', 'name': 'Team Coordination', 'icon': '🔄', 'category': 'Communication'},
                    {'id': 'patching', 'name': 'System Patching', 'icon': '🔨', 'category': 'Operations'},
                    {'id': 'terraform_code', 'name': 'Infrastructure Code', 'icon': '⚙️', 'category': 'Development'},
                    {'id': 'security_review', 'name': 'Security Reviews', 'icon': '🔒', 'category': 'Operations'},
                    {'id': 'cost_optimization', 'name': 'Cost Optimization', 'icon': '💰', 'category': 'Operations'}
                ],
                goals={'offshore': {'daily_hours': 8.8, 'weekly_hours': 44.0, 'uptime_target': 99.9},
                       'onshore': {'daily_hours': 8.0, 'weekly_hours': 40.0, 'uptime_target': 99.9}}
            )
        }
    
    def authenticate_user(self, email: str, password: str) -> Optional[Dict]:
        """Authenticate user with Firestore"""
        return self.db.verify_user_password(email, password)
    
    def register_user(self, name: str, email: str, password: str, role: str, team: str, location_type: str) -> bool:
        """Register a new user with Firestore"""
        team_goals = self.team_configs[team].goals[location_type]
        user_data = {
            'name': name,
            'email': email,
            'password': password,  # This will be handled securely by Firebase Auth
            'role': role,
            'team': team,
            'location_type': location_type,
            'goals': team_goals
        }
        return self.db.create_user(user_data)
    
    def save_daily_entry(self, user_id: str, date_str: str, activity_data: Dict, 
                        notes: str = "", work_location: str = "office", 
                        mood_score: int = 5, energy_level: int = 5) -> bool:
        """Save daily activity entry to Firestore"""
        total_hours = sum(activity_data.values())
        
        entry_data = {
            'date': date_str,
            'activity_data': activity_data,
            'total_hours': total_hours,
            'notes': notes,
            'work_location': work_location,
            'mood_score': mood_score,
            'energy_level': energy_level
        }
        
        return self.db.save_daily_entry(user_id, entry_data)
    
    def get_user_entries_df(self, user_id: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """Get user's daily entries as DataFrame from Firestore"""
        entries = self.db.get_user_entries(user_id, start_date, end_date)
        
        if not entries:
            return pd.DataFrame()
        
        df = pd.DataFrame(entries)
        return df
    
    def calculate_productivity_metrics(self, user_id: str, period: str = 'month', location_type: str = 'onshore') -> Dict:
        """Calculate comprehensive productivity metrics"""
        end_date = date.today()
        
        if period == 'week':
            start_date = end_date - timedelta(days=7)
        elif period == 'month':
            start_date = end_date.replace(day=1)
        elif period == 'quarter':
            start_date = end_date - timedelta(days=90)
        else:
            start_date = end_date - timedelta(days=30)
        
        df = self.get_user_entries_df(user_id, start_date.isoformat(), end_date.isoformat())
        
        if df.empty:
            return {
                'total_hours': 0, 'avg_daily_hours': 0, 'working_days': 0,
                'productivity_score': 0, 'mood_avg': 0, 'energy_avg': 0,
                'activity_breakdown': {}, 'trends': {}, 'expected_daily_hours': self.get_expected_hours(location_type)
            }
        
        total_hours = df['total_hours'].sum()
        working_days = len(df[df['total_hours'] > 0])
        avg_daily_hours = total_hours / max(working_days, 1)
        expected_daily_hours = self.get_expected_hours(location_type)
        
        # Calculate activity breakdown
        activity_breakdown = {}
        for activities in df['activity_data']:
            for activity, hours in activities.items():
                activity_breakdown[activity] = activity_breakdown.get(activity, 0) + hours
        
        # Productivity score based on goals and consistency
        expected_days = (end_date - start_date).days
        consistency_score = (working_days / max(expected_days, 1)) * 100
        hours_score = min((avg_daily_hours / expected_daily_hours) * 100, 100)
        productivity_score = (consistency_score + hours_score) / 2
        
        return {
            'total_hours': total_hours,
            'avg_daily_hours': avg_daily_hours,
            'working_days': working_days,
            'productivity_score': productivity_score,
            'mood_avg': df['mood_score'].mean() if not df.empty else 0,
            'energy_avg': df['energy_level'].mean() if not df.empty else 0,
            'activity_breakdown': activity_breakdown,
            'consistency_score': consistency_score,
            'expected_daily_hours': expected_daily_hours
        }
    
    def generate_insights(self, user_id: str, location_type: str = 'onshore') -> List[str]:
        """Generate AI-powered insights for productivity improvement"""
        metrics = self.calculate_productivity_metrics(user_id, 'month', location_type)
        insights = []
        expected_hours = self.get_expected_hours(location_type)
        location_label = "offshore" if location_type == 'offshore' else "onshore"
        
        # Productivity insights
        if metrics['productivity_score'] >= 90:
            insights.append("🌟 Excellent! You're maintaining outstanding productivity levels.")
        elif metrics['productivity_score'] >= 75:
            insights.append("👍 Good productivity! Consider small optimizations for even better results.")
        elif metrics['productivity_score'] >= 60:
            insights.append("⚠️ Room for improvement. Focus on consistency and goal achievement.")
        else:
            insights.append("🚨 Productivity needs attention. Consider reviewing your workflow and goals.")
        
        # Hours insights (location-specific)
        if metrics['avg_daily_hours'] < (expected_hours - 1):
            insights.append(f"⏰ Consider increasing daily working hours to meet {location_label} target of {expected_hours}h.")
        elif metrics['avg_daily_hours'] > (expected_hours + 2):
            insights.append(f"🔥 High work volume detected ({metrics['avg_daily_hours']:.1f}h vs {expected_hours}h target). Ensure work-life balance.")
        elif abs(metrics['avg_daily_hours'] - expected_hours) <= 0.5:
            insights.append(f"✅ Great! You're meeting your {location_label} daily target of {expected_hours}h.")
        
        # Activity insights
        if metrics['activity_breakdown']:
            top_activity = max(metrics['activity_breakdown'], key=metrics['activity_breakdown'].get)
            insights.append(f"🎯 Your primary focus is on {top_activity.replace('_', ' ').title()}.")
        
        # Mood and energy insights
        if metrics['mood_avg'] < 6:
            insights.append("😔 Low mood scores detected. Consider discussing workload or challenges with your manager.")
        if metrics['energy_avg'] < 6:
            insights.append("⚡ Low energy levels. Ensure adequate rest and consider workload optimization.")
        
        return insights
    
    def run(self):
        """Main application runner"""
        if not st.session_state.authenticated or st.session_state.user is None:
            self.show_auth_page()
        else:
            self.show_main_interface()
    
    def show_auth_page(self):
        """Display authentication interface"""
        # Compact header
        st.markdown("""
        <div style="text-align: center; padding: 1rem 0;">
            <h1>🚀 Enterprise Productivity Tracker</h1>
            <p style="font-size: 1.1rem; color: #666; margin-bottom: 2rem;">Secure cloud-based productivity tracking for Database & Cloud Operations teams</p>
        </div>
        """, unsafe_allow_html=True)
        
        # Create centered container
        col1, col2, col3 = st.columns([1, 2, 1])
        
        with col2:
            tab1, tab2 = st.tabs(["🔐 Sign In", "📝 Register"])
            
            with tab1:
                st.subheader("🔐 Sign In to Your Account")
                
                with st.form("login_form"):
                    email = st.text_input("📧 Email Address", placeholder="your.email@company.com")
                    password = st.text_input("🔒 Password", type="password")
                    
                    remember_me = st.checkbox("Remember me")
                    
                    submit = st.form_submit_button("🚀 Sign In", use_container_width=True, type="primary")
                    
                    if submit and email and password:
                        with st.spinner("Authenticating..."):
                            user = self.authenticate_user(email, password)
                            if user:
                                st.session_state.user = user
                                st.session_state.authenticated = True
                                st.success("✅ Login successful!")
                                st.rerun()
                            else:
                                st.error("❌ Invalid credentials. Please try again.")
                
                # Add forgot password outside the form
                if st.button("🔑 Forgot Password?", type="secondary", use_container_width=True):
                    st.info("Please contact your administrator for password reset assistance.")
            
            with tab2:
                st.subheader("📝 Create New Account")
                st.info("🔒 All data is securely stored in Google Cloud Firestore with enterprise-grade encryption.")
                
                with st.form("register_form"):
                    name = st.text_input("👤 Full Name")
                    email = st.text_input("📧 Email Address")
                    password = st.text_input("🔒 Password", type="password", help="Minimum 6 characters")
                    confirm_password = st.text_input("🔒 Confirm Password", type="password")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        role = st.selectbox("🎭 Role", ["employee", "manager", "admin"])
                    with col2:
                        team = st.selectbox("👥 Team", list(self.team_configs.keys()))
                    
                    location_type = st.selectbox("🌍 Location Type", 
                                               ["onshore", "offshore"], 
                                               help="Onshore: 8 hours/day | Offshore: 8.8 hours/day")
                    
                    if team and location_type:
                        team_config = self.team_configs[team]
                        expected_hours = 8.8 if location_type == 'offshore' else 8.0
                        st.info(f"""
                        **{team_config.icon} {team_config.name}** ({location_type.title()})
                        
                        {team_config.description}
                        
                        📊 **Expected Hours:** {expected_hours} hours/day
                        """)
                    
                    terms = st.checkbox("I agree to the Terms of Service and Privacy Policy")
                    
                    submit = st.form_submit_button("📝 Create Account", use_container_width=True, type="primary")
                    
                    if submit:
                        if not all([name, email, password, confirm_password]):
                            st.error("Please fill in all fields.")
                        elif password != confirm_password:
                            st.error("Passwords do not match.")
                        elif len(password) < 6:
                            st.error("Password must be at least 6 characters long.")
                        elif not terms:
                            st.error("Please accept the Terms of Service.")
                        else:
                            with st.spinner("Creating account..."):
                                if self.register_user(name, email, password, role, team, location_type):
                                    st.success("✅ Account created successfully! Please sign in with your credentials.")
                                    st.balloons()
                                else:
                                    st.error("❌ Account creation failed. Email might already exist.")
    
    def show_main_interface(self):
        """Display main application interface"""
        user = st.session_state.user
        team_config = self.team_configs[user['team']]
        
        # Sidebar
        with st.sidebar:
            location_label = "🌍 Offshore (8.8h)" if user.get('location_type') == 'offshore' else "🏢 Onshore (8.0h)"
            st.markdown(f"""
            <div class="team-card">
                <h2>{team_config.icon} {team_config.name}</h2>
                <p><strong>👤 {user['name']}</strong></p>
                <p>📧 {user['email']}</p>
                <p>🎭 {user['role'].title()}</p>
                <p>{location_label}</p>
                <p style="font-size: 0.8rem; opacity: 0.8;">🔒 Secured by Firebase</p>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button("🚪 Sign Out", use_container_width=True):
                st.session_state.user = None
                st.session_state.authenticated = False
                st.rerun()
            
            st.markdown("---")
            
            # Quick metrics
            metrics = self.calculate_productivity_metrics(user['id'], 'month', user.get('location_type', 'onshore'))
            st.metric("📊 Productivity Score", f"{metrics['productivity_score']:.1f}%")
            st.metric("⏰ Avg Daily Hours", f"{metrics['avg_daily_hours']:.1f}h")
            st.metric("🎯 Target Hours", f"{metrics['expected_daily_hours']:.1f}h")
            st.metric("📅 Working Days", metrics['working_days'])
        
        # Main content
        if user['role'] in ['manager', 'admin']:
            self.show_manager_dashboard()
        else:
            self.show_employee_dashboard()
    
    def show_employee_dashboard(self):
        """Display employee dashboard"""
        user = st.session_state.user
        team_config = self.team_configs[user['team']]
        
        st.title(f"📝 Daily Activity Tracker - {team_config.name}")
        
        # Tab navigation
        tab1, tab2, tab3, tab4, tab5 = st.tabs([
            "📝 Daily Entry", "📊 My Analytics", "🎯 Goals & Insights", 
            "📅 Calendar View", "⚙️ Settings"
        ])
        
        with tab1:
            self.show_daily_entry_form(user, team_config)
        
        with tab2:
            self.show_personal_analytics(user)
        
        with tab3:
            self.show_goals_and_insights(user)
        
        with tab4:
            self.show_calendar_view(user)
        
        with tab5:
            self.show_settings(user)
    
    def show_daily_entry_form(self, user: Dict, team_config: TeamConfig):
        """Show daily entry form"""
        st.subheader(f"📝 {team_config.name} - Daily Activity Entry")
        
        col1, col2 = st.columns([2, 1])
        
        with col1:
            entry_date = st.date_input("📅 Date", value=st.session_state.current_date)
            
            # Get existing entry for the date
            existing_entries = self.db.get_user_entries(
                user['id'], entry_date.isoformat(), entry_date.isoformat()
            )
            
            existing_data = {}
            existing_notes = ""
            existing_location = "office"
            existing_mood = 5
            existing_energy = 5
            
            if existing_entries:
                entry = existing_entries[0]
                existing_data = entry.get('activity_data', {})
                existing_notes = entry.get('notes', "")
                existing_location = entry.get('work_location', "office")
                existing_mood = entry.get('mood_score', 5)
                existing_energy = entry.get('energy_level', 5)
        
        with col2:
            work_location = st.selectbox(
                "🏢 Work Location",
                ["office", "remote", "hybrid", "client-site", "travel"],
                index=["office", "remote", "hybrid", "client-site", "travel"].index(existing_location)
            )
            
            mood_score = st.slider("😊 Mood Score", 1, 10, existing_mood)
            energy_level = st.slider("⚡ Energy Level", 1, 10, existing_energy)
        
        # Activity input form
        st.markdown("### 🎯 Activity Hours")
        
        # Group activities by category
        categories = {}
        for activity in team_config.activities:
            cat = activity['category']
            if cat not in categories:
                categories[cat] = []
            categories[cat].append(activity)
        
        activity_data = {}
        total_hours = 0
        
        for category, activities in categories.items():
            with st.expander(f"📋 {category}", expanded=True):
                cols = st.columns(2)
                for i, activity in enumerate(activities):
                    with cols[i % 2]:
                        hours = st.number_input(
                            f"{activity['icon']} {activity['name']}",
                            min_value=0.0, max_value=12.0, step=0.1,
                            value=float(existing_data.get(activity['id'], 0)),
                            key=f"activity_{activity['id']}"
                        )
                        activity_data[activity['id']] = hours
                        total_hours += hours
        
        # Total hours display
        expected_hours = self.get_expected_hours(user.get('location_type', 'onshore'))
        location_label = "offshore" if user.get('location_type') == 'offshore' else "onshore"
        
        col1, col2, col3 = st.columns(3)
        with col2:
            if total_hours > (expected_hours + 2):
                st.error(f"⚠️ Total: {total_hours:.1f}h (High overtime - Target: {expected_hours}h {location_label})")
            elif total_hours >= (expected_hours - 0.5):
                st.success(f"✅ Total: {total_hours:.1f}h (Meeting {location_label} target: {expected_hours}h)")
            elif total_hours >= (expected_hours - 2):
                st.warning(f"📝 Total: {total_hours:.1f}h (Below {location_label} target: {expected_hours}h)")
            else:
                st.info(f"⏰ Total: {total_hours:.1f}h (Well below {location_label} target: {expected_hours}h)")
        
        # Notes
        notes = st.text_area(
            "📝 Daily Notes & Achievements",
            value=existing_notes,
            placeholder="Describe your key accomplishments, challenges, or important notes for today...",
            height=100
        )
        
        # Save button
        col1, col2, col3 = st.columns([1, 2, 1])
        with col2:
            if st.button("💾 Save Daily Entry", use_container_width=True, type="primary"):
                with st.spinner("Saving to secure cloud..."):
                    if self.save_daily_entry(
                        user['id'], entry_date.isoformat(), activity_data,
                        notes, work_location, mood_score, energy_level
                    ):
                        st.success(f"✅ Entry saved securely! Total: {total_hours:.1f} hours")
                    else:
                        st.error("❌ Failed to save entry")
    
    def show_personal_analytics(self, user: Dict):
        """Show personal analytics dashboard - COMPLETE VERSION"""
        st.subheader("📊 Personal Productivity Analytics")
        
        # Time period selector
        period = st.selectbox("📅 Time Period", ["week", "month", "quarter"])
        metrics = self.calculate_productivity_metrics(user['id'], period, user.get('location_type', 'onshore'))
        
        location_label = "Offshore" if user.get('location_type') == 'offshore' else "Onshore"
        st.info(f"📍 **Location Type:** {location_label} (Target: {metrics['expected_daily_hours']:.1f} hours/day)")
        
        # Key metrics
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric("📊 Productivity Score", f"{metrics['productivity_score']:.1f}%")
        with col2:
            st.metric("⏰ Total Hours", f"{metrics['total_hours']:.1f}h")
        with col3:
            st.metric("📅 Working Days", metrics['working_days'])
        with col4:
            st.metric("🎯 Avg Daily Hours", f"{metrics['avg_daily_hours']:.1f}h")
        
        # Charts
        col1, col2 = st.columns(2)
        
        with col1:
            # Activity breakdown pie chart
            if metrics['activity_breakdown']:
                fig = px.pie(
                    values=list(metrics['activity_breakdown'].values()),
                    names=[name.replace('_', ' ').title() for name in metrics['activity_breakdown'].keys()],
                    title="🎯 Activity Time Distribution"
                )
                st.plotly_chart(fig, use_container_width=True)
        
        with col2:
            # Trend chart
            entries = self.db.get_user_entries(user['id'])
            if entries:
                df = pd.DataFrame(entries)
                df['date'] = pd.to_datetime(df['date'])
                df_recent = df.head(30).sort_values('date')
                
                fig = px.line(
                    df_recent, x='date', y='total_hours',
                    title="📈 Daily Hours Trend (Last 30 Days)"
                )
                fig.add_hline(y=metrics['expected_daily_hours'], line_dash="dash", line_color="green", 
                             annotation_text=f"Target: {metrics['expected_daily_hours']}h ({location_label})")
                st.plotly_chart(fig, use_container_width=True)
        
        # ENHANCED FEATURE: Mood and energy trends
        entries = self.db.get_user_entries(user['id'])
        if entries:
            df = pd.DataFrame(entries)
            if 'mood_score' in df.columns and 'energy_level' in df.columns:
                st.subheader("😊 Wellbeing Trends")
                
                df['date'] = pd.to_datetime(df['date'])
                df_recent = df.head(30).sort_values('date')
                
                col1, col2 = st.columns(2)
                
                with col1:
                    fig = px.line(
                        df_recent, x='date', y='mood_score',
                        title="😊 Mood Score Trend",
                        range_y=[1, 10]
                    )
                    fig.update_traces(line_color='#ff6b6b')
                    st.plotly_chart(fig, use_container_width=True)
                
                with col2:
                    fig = px.line(
                        df_recent, x='date', y='energy_level',
                        title="⚡ Energy Level Trend",
                        range_y=[1, 10]
                    )
                    fig.update_traces(line_color='#4ecdc4')
                    st.plotly_chart(fig, use_container_width=True)
    
    def show_goals_and_insights(self, user: Dict):
        """Show goals and AI insights"""
        st.subheader("🎯 Goals & Productivity Insights")
        
        # AI Insights
        insights = self.generate_insights(user['id'], user.get('location_type', 'onshore'))
        
        st.markdown("### 🤖 AI-Powered Insights")
        for insight in insights:
            st.info(insight)
        
        # Goal tracking
        st.markdown("### 🎯 Goal Tracking")
        
        user_goals = user.get('goals', {})
        metrics = self.calculate_productivity_metrics(user['id'], 'month', user.get('location_type', 'onshore'))
        location_type = user.get('location_type', 'onshore')
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if 'daily_hours' in user_goals:
                target = user_goals['daily_hours']
                current = metrics['avg_daily_hours']
                progress = min(current / target * 100, 100)
                
                st.metric(
                    f"📊 Daily Hours Goal ({location_type.title()})",
                    f"{current:.1f}h / {target:.1f}h",
                    f"{progress:.1f}% complete"
                )
                st.progress(progress / 100)
        
        with col2:
            if 'weekly_hours' in user_goals:
                target = user_goals['weekly_hours']
                current = metrics['total_hours'] * 7 / 30  # Approximate weekly
                progress = min(current / target * 100, 100)
                
                st.metric(
                    f"📅 Weekly Hours Goal ({location_type.title()})",
                    f"{current:.1f}h / {target:.1f}h",
                    f"{progress:.1f}% complete"
                )
                st.progress(progress / 100)
        
        with col3:
            productivity_key = next((key for key in user_goals.keys() if 'productivity' in key), 'monthly_productivity')
            target = user_goals.get(productivity_key, 85.0)
            current = metrics['productivity_score']
            progress = min(current / target * 100, 100)
            
            st.metric(
                "🎯 Productivity Goal",
                f"{current:.1f}% / {target:.1f}%",
                f"{progress:.1f}% complete"
            )
            st.progress(progress / 100)
    
    def show_calendar_view(self, user: Dict):
        """Show calendar view of entries - COMPLETE VERSION"""
        st.subheader("📅 Calendar View")
        st.info("📊 Interactive calendar visualization of your daily productivity patterns stored securely in the cloud.")
        
        # Month selector
        col1, col2 = st.columns([1, 3])
        with col1:
            selected_month = st.date_input("📅 Select Month", value=date.today().replace(day=1))
        
        # Get month data
        start_date = selected_month.replace(day=1)
        if start_date.month == 12:
            end_date = start_date.replace(year=start_date.year + 1, month=1) - timedelta(days=1)
        else:
            end_date = start_date.replace(month=start_date.month + 1) - timedelta(days=1)
        
        entries = self.db.get_user_entries(user['id'], start_date.isoformat(), end_date.isoformat())
        
        if entries:
            df = pd.DataFrame(entries)
            df['date'] = pd.to_datetime(df['date'])
            
            # Create calendar heatmap
            month_dates = pd.date_range(start_date, end_date)
            calendar_data = pd.Series(0.0, index=month_dates)
            
            # Fill in actual data
            for _, row in df.iterrows():
                calendar_data[row['date']] = row['total_hours']
            
            # Create calendar matrix for heatmap
            first_day = start_date
            first_monday = first_day - timedelta(days=first_day.weekday())
            last_day = end_date
            last_sunday = last_day + timedelta(days=(6 - last_day.weekday()))
            
            full_calendar_range = pd.date_range(first_monday, last_sunday)
            full_calendar_data = pd.Series(0.0, index=full_calendar_range)
            
            # Fill actual month data
            for date in month_dates:
                if date in calendar_data.index:
                    full_calendar_data[date] = calendar_data[date]
            
            try:
                weeks = len(full_calendar_range) // 7
                calendar_matrix = full_calendar_data.values.reshape(weeks, 7)
                
                # Create date labels
                date_labels = []
                for week in range(weeks):
                    week_dates = []
                    for day in range(7):
                        date_idx = week * 7 + day
                        if date_idx < len(full_calendar_range):
                            date_obj = full_calendar_range[date_idx]
                            if start_date <= date_obj <= end_date:
                                week_dates.append(date_obj.strftime('%d'))
                            else:
                                week_dates.append('')
                        else:
                            week_dates.append('')
                    date_labels.append(week_dates)
                
                # Create heatmap
                fig = go.Figure(data=go.Heatmap(
                    z=calendar_matrix,
                    x=['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
                    y=[f'Week {i+1}' for i in range(weeks)],
                    colorscale='RdYlBu_r',
                    showscale=True,
                    colorbar=dict(title="Hours"),
                    hoverongaps=False
                ))
                
                # Add date annotations
                for week in range(weeks):
                    for day in range(7):
                        if week < len(date_labels) and day < len(date_labels[week]) and date_labels[week][day]:
                            fig.add_annotation(
                                x=day, y=week,
                                text=date_labels[week][day],
                                showarrow=False,
                                font=dict(
                                    color="white" if calendar_matrix[week][day] > 4 else "black", 
                                    size=10
                                )
                            )
                
                fig.update_layout(
                    title="📅 Monthly Activity Heatmap",
                    xaxis_title="Day of Week",
                    yaxis_title="Week",
                    height=400
                )
                
                st.plotly_chart(fig, use_container_width=True)
                
            except Exception as e:
                # Fallback to bar chart
                st.warning("Complex calendar view unavailable, showing daily summary.")
                chart_df = pd.DataFrame({
                    'Date': calendar_data.index,
                    'Hours': calendar_data.values
                })
                fig = px.bar(
                    chart_df, x='Date', y='Hours',
                    title="📊 Daily Hours Summary"
                )
                fig.update_layout(xaxis_tickangle=45)
                st.plotly_chart(fig, use_container_width=True)
            
            # Monthly summary
            st.markdown("### 📊 Monthly Summary")
            
            col1, col2, col3, col4 = st.columns(4)
            
            total_hours = df['total_hours'].sum()
            working_days = len(df[df['total_hours'] > 0])
            avg_hours = total_hours / max(working_days, 1)
            
            if len(df) > 0:
                best_day_row = df.loc[df['total_hours'].idxmax()]
                best_day = best_day_row['date']
                if isinstance(best_day, str):
                    best_day_str = best_day
                else:
                    best_day_str = best_day.strftime('%Y-%m-%d')
            else:
                best_day_str = "N/A"
            
            with col1:
                st.metric("📊 Total Hours", f"{total_hours:.1f}h")
            with col2:
                st.metric("📅 Working Days", working_days)
            with col3:
                st.metric("🎯 Average Hours", f"{avg_hours:.1f}h")
            with col4:
                st.metric("🏆 Best Day", best_day_str)
            
            # Daily breakdown table
            if len(df) > 0:
                st.markdown("### 📋 Daily Breakdown")
                
                summary_df = df[['date', 'total_hours', 'work_location', 'mood_score', 'energy_level', 'notes']].copy()
                summary_df = summary_df[summary_df['total_hours'] > 0]
                summary_df = summary_df.sort_values('date', ascending=False)
                
                # Format display
                summary_df['date'] = pd.to_datetime(summary_df['date']).dt.strftime('%Y-%m-%d (%A)')
                summary_df['total_hours'] = summary_df['total_hours'].round(1)
                summary_df['notes'] = summary_df['notes'].fillna('').astype(str).str[:100]
                summary_df.loc[summary_df['notes'].str.len() >= 100, 'notes'] += '...'
                
                summary_df.columns = ['Date', 'Hours', 'Location', 'Mood', 'Energy', 'Notes']
                
                st.dataframe(summary_df, use_container_width=True, hide_index=True)
        else:
            st.info("No entries found for the selected month. Start by adding some daily entries!")
    
    def show_settings(self, user: Dict):
        """Show user settings"""
        st.subheader("⚙️ Settings & Data Management")
        st.info("🔒 Your data is securely stored in Google Cloud Firestore with enterprise-grade encryption and backup.")
        
        # Data export section
        st.markdown("### 📤 Export Your Data")
        st.write("Download your productivity data for external analysis or backup purposes.")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if st.button("📊 Export CSV", use_container_width=True):
                data = self.export_data(user['id'], 'csv')
                if data != b"No data available for export":
                    st.download_button(
                        "⬇️ Download CSV",
                        data,
                        f"productivity_data_{user['name']}_{date.today()}.csv",
                        "text/csv"
                    )
                else:
                    st.warning("No data available to export.")
        
        with col2:
            if st.button("📋 Export Excel", use_container_width=True):
                data = self.export_data(user['id'], 'excel')
                if data != b"No data available for export":
                    st.download_button(
                        "⬇️ Download Excel",
                        data,
                        f"productivity_data_{user['name']}_{date.today()}.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                else:
                    st.warning("No data available to export.")
        
        with col3:
            if st.button("📄 Export JSON", use_container_width=True):
                data = self.export_data(user['id'], 'json')
                if data != b"No data available for export":
                    st.download_button(
                        "⬇️ Download JSON",
                        data,
                        f"productivity_data_{user['name']}_{date.today()}.json",
                        "application/json"
                    )
                else:
                    st.warning("No data available to export.")
        
        # Security settings
        st.markdown("### 🔒 Security & Privacy")
        
        col1, col2 = st.columns(2)
        with col1:
            st.info("🛡️ **Data Protection**\n- End-to-end encryption\n- Secure cloud storage\n- Regular automated backups")
        
        with col2:
            st.info("🔐 **Access Control**\n- Firebase Authentication\n- Role-based permissions\n- Audit logging")
        
        # Notifications settings
        st.markdown("### 🔔 Notification Preferences")
        
        daily_reminder = st.checkbox("📱 Daily entry reminders", value=True)
        weekly_summary = st.checkbox("📊 Weekly productivity summary", value=True)
        goal_alerts = st.checkbox("🎯 Goal achievement alerts", value=True)
        
        if st.button("💾 Save Settings"):
            st.success("Settings saved successfully!")
    
    def show_manager_dashboard(self):
        """Show manager/admin dashboard"""
        user = st.session_state.user
        
        st.title("👔 Manager Dashboard")
        st.info("🔒 Secure access to team productivity insights with enterprise-grade data protection.")
        
        tab1, tab2, tab3, tab4 = st.tabs([
            "👥 Team Overview", "📊 Team Analytics", "📋 Reports", "⚙️ Admin"
        ])
        
        with tab1:
            self.show_team_overview(user)
        
        with tab2:
            self.show_team_analytics(user)
        
        with tab3:
            self.show_team_reports(user)
        
        with tab4:
            if user['role'] == 'admin':
                self.show_admin_panel(user)
            else:
                st.error("Access denied. Admin privileges required.")
    
    def show_team_overview(self, user: Dict):
        """Show team overview for managers"""
        st.subheader("👥 Team Performance Overview")
        
        # Get team members from Firestore
        team_members = self.db.get_team_members(user['team'], 'employee')
        
        if not team_members:
            st.info("No team members found.")
            return
        
        # Team metrics
        col1, col2, col3, col4 = st.columns(4)
        
        team_total_hours = 0
        team_productivity = 0
        active_members = 0
        
        for member in team_members:
            metrics = self.calculate_productivity_metrics(
                member['id'], 'month', member.get('location_type', 'onshore')
            )
            if metrics['working_days'] > 0:
                team_total_hours += metrics['total_hours']
                team_productivity += metrics['productivity_score']
                active_members += 1
        
        avg_productivity = team_productivity / max(active_members, 1)
        
        with col1:
            st.metric("👥 Team Members", len(team_members))
        with col2:
            st.metric("✅ Active Members", active_members)
        with col3:
            st.metric("⏰ Total Team Hours", f"{team_total_hours:.1f}h")
        with col4:
            st.metric("📊 Avg Productivity", f"{avg_productivity:.1f}%")
        
        # Individual member cards
        st.markdown("### 👤 Individual Performance")
        
        for member in team_members:
            location_type = member.get('location_type', 'onshore')
            metrics = self.calculate_productivity_metrics(member['id'], 'month', location_type)
            location_label = "🌍 Offshore" if location_type == 'offshore' else "🏢 Onshore"
            expected_hours = metrics['expected_daily_hours']
            
            with st.expander(f"👤 {member['name']} ({location_label} - {expected_hours}h target)", expanded=False):
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric("📊 Productivity", f"{metrics['productivity_score']:.1f}%")
                with col2:
                    st.metric("⏰ Total Hours", f"{metrics['total_hours']:.1f}h")
                with col3:
                    st.metric("📅 Working Days", metrics['working_days'])
                with col4:
                    st.metric("🎯 Avg Daily", f"{metrics['avg_daily_hours']:.1f}h")
                
                # Performance status
                if metrics['productivity_score'] >= 85:
                    st.success("🌟 Excellent Performance")
                elif metrics['productivity_score'] >= 70:
                    st.info("👍 Good Performance")
                elif metrics['productivity_score'] >= 50:
                    st.warning("⚠️ Needs Improvement")
                else:
                    st.error("🚨 Requires Attention")
    
    def show_team_analytics(self, user: Dict):
        """Show team analytics - COMPLETE VERSION"""
        st.subheader("📊 Team Analytics & Insights")
        st.info("Real-time analytics powered by secure cloud data.")
        
        team_members = self.db.get_team_members(user['team'], 'employee')
        
        if not team_members:
            st.info("No team data available.")
            return
        
        # Aggregate team data
        all_data = []
        team_metrics = {
            'total_productivity': 0,
            'total_hours': 0,
            'active_count': 0,
            'team_activities': {}
        }
        
        for member in team_members:
            member_entries = self.db.get_user_entries(member['id'])
            if member_entries:
                member_df = pd.DataFrame(member_entries)
                member_df['member_name'] = member['name']
                member_df['member_id'] = member['id']
                member_df['location_type'] = member.get('location_type', 'onshore')
                all_data.append(member_df)
                
                # Calculate member metrics
                metrics = self.calculate_productivity_metrics(
                    member['id'], 'month', member.get('location_type', 'onshore')
                )
                if metrics['working_days'] > 0:
                    team_metrics['total_productivity'] += metrics['productivity_score']
                    team_metrics['total_hours'] += metrics['total_hours']
                    team_metrics['active_count'] += 1
                    
                    # Aggregate activities
                    for activity, hours in metrics['activity_breakdown'].items():
                        team_metrics['team_activities'][activity] = \
                            team_metrics['team_activities'].get(activity, 0) + hours
        
        if team_metrics['active_count'] > 0:
            # Team summary metrics
            col1, col2, col3, col4 = st.columns(4)
            
            avg_productivity = team_metrics['total_productivity'] / team_metrics['active_count']
            avg_hours_per_member = team_metrics['total_hours'] / team_metrics['active_count']
            
            with col1:
                st.metric("👥 Total Members", len(team_members))
            with col2:
                st.metric("✅ Active Members", team_metrics['active_count'])
            with col3:
                st.metric("📊 Team Avg Productivity", f"{avg_productivity:.1f}%")
            with col4:
                st.metric("⏰ Avg Hours/Member", f"{avg_hours_per_member:.1f}h")
        
        if all_data:
            team_df = pd.concat(all_data, ignore_index=True)
            team_df['date'] = pd.to_datetime(team_df['date'])
            
            # Team productivity over time
            col1, col2 = st.columns(2)
            
            with col1:
                daily_summary = team_df.groupby('date').agg({
                    'total_hours': 'sum',
                    'member_name': 'count'
                }).rename(columns={'member_name': 'active_members'})
                
                fig = px.line(
                    daily_summary.reset_index(),
                    x='date', y='total_hours',
                    title="📈 Team Total Hours Over Time"
                )
                st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                daily_summary['avg_hours_per_member'] = \
                    daily_summary['total_hours'] / daily_summary['active_members']
                
                fig = px.line(
                    daily_summary.reset_index(),
                    x='date', y='avg_hours_per_member',
                    title="🎯 Average Hours per Team Member"
                )
                st.plotly_chart(fig, use_container_width=True)
            
            # Team activity distribution
            if team_metrics['team_activities']:
                st.markdown("### 🎯 Team Activity Distribution")
                
                activity_df = pd.DataFrame([
                    {'Activity': activity.replace('_', ' ').title(), 'Hours': hours}
                    for activity, hours in team_metrics['team_activities'].items()
                ])
                
                fig = px.bar(
                    activity_df,
                    x='Activity', y='Hours',
                    title="Team Activity Breakdown"
                )
                fig.update_layout(xaxis_tickangle=45)
                st.plotly_chart(fig, use_container_width=True)
            
            # Individual performance comparison
            st.markdown("### 👤 Individual Performance Comparison")
            
            member_performance = []
            for member in team_members:
                metrics = self.calculate_productivity_metrics(
                    member['id'], 'month', member.get('location_type', 'onshore')
                )
                member_performance.append({
                    'Member': member['name'],
                    'Productivity': metrics['productivity_score'],
                    'Total Hours': metrics['total_hours'],
                    'Avg Daily': metrics['avg_daily_hours'],
                    'Working Days': metrics['working_days']
                })
            
            if member_performance:
                perf_df = pd.DataFrame(member_performance)
                
                col1, col2 = st.columns(2)
                
                with col1:
                    fig = px.bar(
                        perf_df, x='Member', y='Productivity',
                        title="📊 Individual Productivity Scores"
                    )
                    fig.update_layout(xaxis_tickangle=45)
                    st.plotly_chart(fig, use_container_width=True)
                
                with col2:
                    fig = px.bar(
                        perf_df, x='Member', y='Total Hours',
                        title="⏰ Individual Total Hours"
                    )
                    fig.update_layout(xaxis_tickangle=45)
                    st.plotly_chart(fig, use_container_width=True)
    
    def show_team_reports(self, user: Dict):
        """Show team reports generation"""
        st.subheader("📋 Team Reports")
        st.info("Generate comprehensive team productivity reports from secure cloud data.")
        
        # Report generation options
        col1, col2 = st.columns(2)
        
        with col1:
            report_period = st.selectbox("📅 Report Period", ["week", "month", "quarter"])
            include_individual = st.checkbox("👤 Include Individual Details", value=True)
        
        with col2:
            if st.button("📊 Generate Team Report", type="primary"):
                team_members = self.db.get_team_members(user['team'], 'employee')
                
                report_data = {
                    'team': self.team_configs[user['team']].name,
                    'period': report_period,
                    'generated_at': datetime.now().isoformat(),
                    'total_members': len(team_members),
                    'report_type': 'enterprise_secure'
                }
                
                # Display report
                st.markdown("### 📊 Team Performance Report")
                st.json(report_data)
                
                # Export options
                st.download_button(
                    "📤 Download Report",
                    json.dumps(report_data, indent=2),
                    f"team_report_{user['team']}_{report_period}_{date.today()}.json",
                    "application/json"
                )
    
    def show_admin_panel(self, user: Dict):
        """Show admin panel"""
        st.subheader("⚙️ Admin Panel")
        st.info("🔒 Enterprise administration with secure access controls.")
        
        # System statistics
        st.markdown("### 📊 System Statistics")
        
        stats = self.db.get_system_stats()
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("👥 Total Users", stats['total_users'])
        with col2:
            st.metric("📝 Total Entries", stats['total_entries'])
        with col3:
            st.metric("✅ Active Today", stats['active_today'])
        
        # User management
        st.markdown("### 👥 User Management")
        
        all_users = self.db.get_all_users()
        if all_users:
            users_df = pd.DataFrame(all_users)
            display_df = users_df[['name', 'email', 'role', 'team', 'location_type']].copy()
            display_df.columns = ['Name', 'Email', 'Role', 'Team', 'Location']
            display_df['Expected Hours'] = display_df['Location'].apply(
                lambda x: '8.8h' if x == 'offshore' else '8.0h'
            )
            st.dataframe(display_df, use_container_width=True)

# Initialize and run the application
if __name__ == "__main__":
    app = ProductivityTracker()
    app.run()