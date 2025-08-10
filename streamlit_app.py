import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import sqlite3
import hashlib
from datetime import datetime, timedelta, date
import json
import io
import base64
from typing import Dict, List, Optional
import numpy as np
from dataclasses import dataclass
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Configure Streamlit page
st.set_page_config(
    page_title="Advanced Productivity Tracker",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better styling
st.markdown("""
<style>
    .main > div {
        padding-top: 2rem;
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
    location_type: str  # 'offshore' or 'onshore'
    goals: Dict[str, float]

class DatabaseManager:
    def __init__(self, db_name="productivity_tracker.db"):
        self.db_name = db_name
        self.init_database()
    
    def init_database(self):
        """Initialize database tables"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        
        # Users table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                team TEXT NOT NULL,
                location_type TEXT NOT NULL DEFAULT 'onshore',
                goals TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Daily entries table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                date TEXT NOT NULL,
                activity_data TEXT NOT NULL,
                total_hours REAL NOT NULL,
                notes TEXT,
                work_location TEXT,
                mood_score INTEGER,
                energy_level INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id),
                UNIQUE(user_id, date)
            )
        """)
        
        # Goals table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                goal_type TEXT NOT NULL,
                target_value REAL NOT NULL,
                current_value REAL DEFAULT 0,
                period TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                status TEXT DEFAULT 'active',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)
        
        # Team notifications table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                message TEXT NOT NULL,
                type TEXT NOT NULL,
                read_status BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users (id)
            )
        """)
        
        conn.commit()
        conn.close()
    
    def execute_query(self, query: str, params: tuple = ()) -> List:
        """Execute a query and return results"""
        conn = sqlite3.connect(self.db_name)
        cursor = conn.cursor()
        cursor.execute(query, params)
        results = cursor.fetchall()
        conn.commit()
        conn.close()
        return results
    
    def get_user(self, email: str) -> Optional[Dict]:
        """Get user by email"""
        results = self.execute_query(
            "SELECT * FROM users WHERE email = ?", (email,)
        )
        if results:
            return {
                'id': results[0][0], 'name': results[0][1], 'email': results[0][2],
                'password_hash': results[0][3], 'role': results[0][4], 'team': results[0][5],
                'location_type': results[0][6] if len(results[0]) > 6 else 'onshore',
                'goals': json.loads(results[0][7]) if len(results[0]) > 7 and results[0][7] else {}
            }
        return None
    
    def create_user(self, user_data: Dict) -> bool:
        """Create a new user"""
        try:
            self.execute_query("""
                INSERT INTO users (id, name, email, password_hash, role, team, location_type, goals)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                user_data['id'], user_data['name'], user_data['email'],
                user_data['password_hash'], user_data['role'], user_data['team'],
                user_data['location_type'], json.dumps(user_data.get('goals', {}))
            ))
            return True
        except:
            return False

class ProductivityTracker:
    def __init__(self):
        self.db = DatabaseManager()
        self.team_configs = self._get_team_configurations()
        self._init_session_state()
    
    def _init_session_state(self):
        """Initialize Streamlit session state"""
        if 'user' not in st.session_state:
            st.session_state.user = None
        if 'current_date' not in st.session_state:
            st.session_state.current_date = date.today()
        if 'selected_employee' not in st.session_state:
            st.session_state.selected_employee = None
    
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
    
    def hash_password(self, password: str) -> str:
        """Hash password for security"""
        return hashlib.sha256(password.encode()).hexdigest()
    
    def authenticate_user(self, email: str, password: str) -> Optional[Dict]:
        """Authenticate user login"""
        user = self.db.get_user(email)
        if user and user['password_hash'] == self.hash_password(password):
            return user
        return None
    
    def register_user(self, name: str, email: str, password: str, role: str, team: str, location_type: str) -> bool:
        """Register a new user"""
        team_goals = self.team_configs[team].goals[location_type]
        user_data = {
            'id': hashlib.md5(email.encode()).hexdigest()[:12],
            'name': name,
            'email': email,
            'password_hash': self.hash_password(password),
            'role': role,
            'team': team,
            'location_type': location_type,
            'goals': team_goals
        }
        return self.db.create_user(user_data)
    
    def save_daily_entry(self, user_id: str, date_str: str, activity_data: Dict, 
                        notes: str = "", work_location: str = "office", 
                        mood_score: int = 5, energy_level: int = 5) -> bool:
        """Save daily activity entry"""
        total_hours = sum(activity_data.values())
        
        try:
            self.db.execute_query("""
                INSERT OR REPLACE INTO daily_entries 
                (user_id, date, activity_data, total_hours, notes, work_location, mood_score, energy_level, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
            """, (
                user_id, date_str, json.dumps(activity_data), total_hours,
                notes, work_location, mood_score, energy_level
            ))
            return True
        except Exception as e:
            st.error(f"Error saving entry: {e}")
            return False
    
    def get_user_entries(self, user_id: str, start_date: str = None, end_date: str = None) -> pd.DataFrame:
        """Get user's daily entries as DataFrame"""
        query = "SELECT * FROM daily_entries WHERE user_id = ?"
        params = [user_id]
        
        if start_date and end_date:
            query += " AND date BETWEEN ? AND ?"
            params.extend([start_date, end_date])
        
        query += " ORDER BY date DESC"
        
        results = self.db.execute_query(query, tuple(params))
        
        if not results:
            return pd.DataFrame()
        
        df = pd.DataFrame(results, columns=[
            'id', 'user_id', 'date', 'activity_data', 'total_hours',
            'notes', 'work_location', 'mood_score', 'energy_level',
            'created_at', 'updated_at'
        ])
        
        # Parse activity data
        df['activities'] = df['activity_data'].apply(lambda x: json.loads(x) if x else {})
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
        
        df = self.get_user_entries(user_id, start_date.isoformat(), end_date.isoformat())
        
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
        for activities in df['activities']:
            for activity, hours in activities.items():
                activity_breakdown[activity] = activity_breakdown.get(activity, 0) + hours
        
        # Productivity score based on goals and consistency (adjusted for location)
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
    
    def export_data(self, user_id: str, format: str = 'csv') -> bytes:
        """Export user data in various formats"""
        df = self.get_user_entries(user_id)
        
        if format == 'csv':
            return df.to_csv(index=False).encode()
        elif format == 'excel':
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
                df.to_excel(writer, sheet_name='Daily_Entries', index=False)
                
                # Add metrics sheet
                metrics = self.calculate_productivity_metrics(user_id)
                metrics_df = pd.DataFrame([metrics])
                metrics_df.to_excel(writer, sheet_name='Metrics', index=False)
            
            return output.getvalue()
    
    def run(self):
        """Main application runner"""
        if st.session_state.user is None:
            self.show_login_page()
        else:
            self.show_main_interface()
    
    def show_login_page(self):
        """Display login/registration interface"""
        st.title("🚀 Advanced Productivity Tracker")
        st.markdown("### Enterprise-grade productivity tracking for Database & Cloud Operations teams")
        
        tab1, tab2 = st.tabs(["🔐 Login", "📝 Register"])
        
        with tab1:
            st.subheader("Login to Your Account")
            with st.form("login_form"):
                email = st.text_input("Email Address", placeholder="your.email@company.com")
                password = st.text_input("Password", type="password")
                submit = st.form_submit_button("🚀 Login", use_container_width=True)
                
                if submit:
                    user = self.authenticate_user(email, password)
                    if user:
                        st.session_state.user = user
                        st.success("Login successful!")
                        st.rerun()
                    else:
                        st.error("Invalid credentials!")
        
        with tab2:
            st.subheader("Create New Account")
            with st.form("register_form"):
                name = st.text_input("Full Name")
                email = st.text_input("Email Address")
                password = st.text_input("Password", type="password")
                role = st.selectbox("Role", ["employee", "manager", "admin"])
                team = st.selectbox("Team", list(self.team_configs.keys()))
                location_type = st.selectbox("Location Type", 
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
                
                submit = st.form_submit_button("📝 Register", use_container_width=True)
                
                if submit:
                    if self.register_user(name, email, password, role, team, location_type):
                        st.success("Registration successful! Please login with your credentials.")
                    else:
                        st.error("Registration failed! Email might already exist.")
    
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
            </div>
            """, unsafe_allow_html=True)
            
            if st.button("🚪 Logout", use_container_width=True):
                st.session_state.user = None
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
            existing_entry = self.get_user_entries(
                user['id'], entry_date.isoformat(), entry_date.isoformat()
            )
            
            existing_data = {}
            existing_notes = ""
            existing_location = "office"
            existing_mood = 5
            existing_energy = 5
            
            if not existing_entry.empty:
                entry = existing_entry.iloc[0]
                existing_data = entry['activities']
                existing_notes = entry['notes'] or ""
                existing_location = entry['work_location'] or "office"
                existing_mood = entry['mood_score'] or 5
                existing_energy = entry['energy_level'] or 5
        
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
                if self.save_daily_entry(
                    user['id'], entry_date.isoformat(), activity_data,
                    notes, work_location, mood_score, energy_level
                ):
                    st.success(f"✅ Entry saved! Total: {total_hours:.1f} hours")
                else:
                    st.error("❌ Failed to save entry")
    
    def show_personal_analytics(self, user: Dict):
        """Show personal analytics dashboard"""
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
            df = self.get_user_entries(user['id'])
            if not df.empty:
                df['date'] = pd.to_datetime(df['date'])
                df_recent = df.head(30).sort_values('date')
                
                fig = px.line(
                    df_recent, x='date', y='total_hours',
                    title="📈 Daily Hours Trend (Last 30 Days)"
                )
                fig.add_hline(y=metrics['expected_daily_hours'], line_dash="dash", line_color="green", 
                             annotation_text=f"Target: {metrics['expected_daily_hours']}h ({location_label})")
                st.plotly_chart(fig, use_container_width=True)
        
        # Mood and energy trends
        if not df.empty and 'mood_score' in df.columns:
            st.subheader("😊 Wellbeing Trends")
            
            col1, col2 = st.columns(2)
            
            with col1:
                fig = px.line(
                    df_recent, x='date', y='mood_score',
                    title="😊 Mood Score Trend"
                )
                st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                fig = px.line(
                    df_recent, x='date', y='energy_level',
                    title="⚡ Energy Level Trend"
                )
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
        """Show calendar view of entries"""
        st.subheader("📅 Calendar View")
        
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
        
        df = self.get_user_entries(user['id'], start_date.isoformat(), end_date.isoformat())
        
        # Create calendar grid
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            
            # Create a complete date range for the month
            month_dates = pd.date_range(start_date, end_date)
            calendar_data = df.set_index('date')['total_hours'].reindex(month_dates, fill_value=0)
            
            # Find the first Monday of the calendar (might be in previous month)
            first_day = start_date
            first_monday = first_day - timedelta(days=first_day.weekday())
            
            # Find the last Sunday of the calendar (might be in next month) 
            last_day = end_date
            last_sunday = last_day + timedelta(days=(6 - last_day.weekday()))
            
            # Create full calendar range (complete weeks)
            full_calendar_range = pd.date_range(first_monday, last_sunday)
            
            # Reindex with full calendar range, filling missing values with 0
            full_calendar_data = calendar_data.reindex(full_calendar_range, fill_value=0)
            
            # Now we can safely reshape into weeks (should be divisible by 7)
            try:
                weeks = len(full_calendar_range) // 7
                calendar_matrix = full_calendar_data.values.reshape(weeks, 7)
                
                # Create date labels for the heatmap
                date_labels = []
                for i in range(weeks):
                    week_dates = []
                    for j in range(7):
                        date_idx = i * 7 + j
                        if date_idx < len(full_calendar_range):
                            date_obj = full_calendar_range[date_idx]
                            if start_date <= date_obj <= end_date:
                                week_dates.append(date_obj.strftime('%d'))
                            else:
                                week_dates.append('')  # Days outside current month
                        else:
                            week_dates.append('')
                    date_labels.append(week_dates)
                
                # Create the heatmap
                fig = go.Figure(data=go.Heatmap(
                    z=calendar_matrix,
                    x=['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
                    y=[f'Week {i+1}' for i in range(weeks)],
                    colorscale='Blues',
                    showscale=True,
                    hoverongaps=False,
                    colorbar=dict(title="Hours")
                ))
                
                # Add text annotations for dates
                for i in range(weeks):
                    for j in range(7):
                        if i < len(date_labels) and j < len(date_labels[i]) and date_labels[i][j]:
                            fig.add_annotation(
                                x=j, y=i,
                                text=date_labels[i][j],
                                showarrow=False,
                                font=dict(color="white" if calendar_matrix[i][j] > 4 else "black", size=10)
                            )
                
                fig.update_layout(
                    title="📅 Monthly Activity Heatmap",
                    xaxis_title="Day of Week",
                    yaxis_title="Week",
                    height=400
                )
                
                st.plotly_chart(fig, use_container_width=True)
                
            except Exception as e:
                # Fallback to simple bar chart if heatmap fails
                st.warning("Calendar heatmap unavailable, showing daily hours chart instead.")
                
                # Create a proper dataframe for the bar chart
                chart_df = pd.DataFrame({
                    'Date': calendar_data.index,
                    'Hours': calendar_data.values
                })
                
                fig = px.bar(
                    chart_df,
                    x='Date',
                    y='Hours',
                    title="📊 Daily Hours for Selected Month"
                )
                fig.update_layout(xaxis_tickangle=45)
                st.plotly_chart(fig, use_container_width=True)
        
        else:
            st.info("No data available for the selected month.")
        
        # Monthly summary
        if not df.empty:
            st.markdown("### 📊 Monthly Summary")
            
            col1, col2, col3, col4 = st.columns(4)
            
            total_hours = df['total_hours'].sum()
            working_days = len(df[df['total_hours'] > 0])
            avg_hours = total_hours / max(working_days, 1)
            
            # Find best day safely
            if len(df) > 0:
                best_day_idx = df['total_hours'].idxmax()
                best_day = df.loc[best_day_idx, 'date']
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
            
            # Show detailed breakdown
            if len(df) > 0:
                st.markdown("### 📋 Daily Breakdown")
                
                # Create a summary table
                summary_df = df[['date', 'total_hours', 'work_location', 'mood_score', 'energy_level', 'notes']].copy()
                summary_df = summary_df[summary_df['total_hours'] > 0]  # Only show working days
                summary_df = summary_df.sort_values('date', ascending=False)
                
                # Format the display
                summary_df['date'] = pd.to_datetime(summary_df['date']).dt.strftime('%Y-%m-%d (%A)')
                summary_df['total_hours'] = summary_df['total_hours'].round(1)
                summary_df['notes'] = summary_df['notes'].fillna('').str[:100] + '...'  # Truncate long notes
                
                summary_df.columns = ['Date', 'Hours', 'Location', 'Mood', 'Energy', 'Notes']
                
                st.dataframe(
                    summary_df,
                    use_container_width=True,
                    hide_index=True
                )
        
        else:
            st.info("No entries found for the selected month. Start by adding some daily entries!")
    
    def show_settings(self, user: Dict):
        """Show user settings"""
        st.subheader("⚙️ Settings & Data Management")
        
        # Export data
        st.markdown("### 📤 Export Data")
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("📊 Export CSV", use_container_width=True):
                data = self.export_data(user['id'], 'csv')
                st.download_button(
                    "⬇️ Download CSV",
                    data,
                    f"productivity_data_{user['name']}_{date.today()}.csv",
                    "text/csv"
                )
        
        with col2:
            if st.button("📋 Export Excel", use_container_width=True):
                data = self.export_data(user['id'], 'excel')
                st.download_button(
                    "⬇️ Download Excel",
                    data,
                    f"productivity_data_{user['name']}_{date.today()}.xlsx",
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
        
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
            self.show_admin_panel(user)
    
    def show_team_overview(self, user: Dict):
        """Show team overview for managers"""
        st.subheader("👥 Team Performance Overview")
        
        # Get team members
        team_members = self.db.execute_query(
            "SELECT user_id, name, location_type FROM users WHERE team = ? AND role = 'employee'",
            (user['team'],)
        )
        
        if not team_members:
            st.info("No team members found.")
            return
        
        # Team metrics
        col1, col2, col3, col4 = st.columns(4)
        
        team_total_hours = 0
        team_productivity = 0
        active_members = 0
        
        for member_id, member_name, location_type in team_members:
            metrics = self.calculate_productivity_metrics(member_id, 'month', location_type or 'onshore')
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
        
        for member_id, member_name, location_type in team_members:
            location_type = location_type or 'onshore'  # Default to onshore if None
            metrics = self.calculate_productivity_metrics(member_id, 'month', location_type)
            location_label = "🌍 Offshore" if location_type == 'offshore' else "🏢 Onshore"
            expected_hours = metrics['expected_daily_hours']
            
            with st.expander(f"👤 {member_name} ({location_label} - {expected_hours}h target)", expanded=False):
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
        """Show team analytics"""
        st.subheader("📊 Team Analytics & Insights")
        
        # Team productivity trends
        team_members = self.db.execute_query(
            "SELECT user_id, name, location_type FROM users WHERE team = ? AND role = 'employee'",
            (user['team'],)
        )
        
        if not team_members:
            st.info("No team data available.")
            return
        
        # Aggregate team data
        all_data = []
        for member_id, member_name, location_type in team_members:
            df = self.get_user_entries(member_id)
            if not df.empty:
                df['member_name'] = member_name
                df['location_type'] = location_type or 'onshore'
                all_data.append(df)
        
        if all_data:
            team_df = pd.concat(all_data, ignore_index=True)
            team_df['date'] = pd.to_datetime(team_df['date'])
            
            # Team productivity over time
            daily_summary = team_df.groupby('date').agg({
                'total_hours': 'sum',
                'member_name': 'count'
            }).rename(columns={'member_name': 'active_members'})
            
            daily_summary['avg_hours_per_member'] = daily_summary['total_hours'] / daily_summary['active_members']
            
            col1, col2 = st.columns(2)
            
            with col1:
                fig = px.line(
                    daily_summary.reset_index(),
                    x='date', y='total_hours',
                    title="📈 Team Total Hours Over Time"
                )
                st.plotly_chart(fig, use_container_width=True)
            
            with col2:
                fig = px.line(
                    daily_summary.reset_index(),
                    x='date', y='avg_hours_per_member',
                    title="🎯 Average Hours per Team Member"
                )
                st.plotly_chart(fig, use_container_width=True)
            
            # Activity distribution across team
            activity_totals = {}
            for activities in team_df['activities']:
                for activity, hours in activities.items():
                    activity_totals[activity] = activity_totals.get(activity, 0) + hours
            
            if activity_totals:
                fig = px.bar(
                    x=[name.replace('_', ' ').title() for name in activity_totals.keys()],
                    y=list(activity_totals.values()),
                    title="🎯 Team Activity Distribution"
                )
                fig.update_xaxis(tickangle=45)
                st.plotly_chart(fig, use_container_width=True)
    
    def show_team_reports(self, user: Dict):
        """Show team reports generation"""
        st.subheader("📋 Team Reports")
        
        # Report generation options
        col1, col2 = st.columns(2)
        
        with col1:
            report_period = st.selectbox("📅 Report Period", ["week", "month", "quarter"])
            include_individual = st.checkbox("👤 Include Individual Details", value=True)
            include_insights = st.checkbox("🤖 Include AI Insights", value=True)
        
        with col2:
            if st.button("📊 Generate Team Report", type="primary"):
                # Generate comprehensive team report
                team_members = self.db.execute_query(
                    "SELECT user_id, name FROM users WHERE team = ? AND role = 'employee'",
                    (user['team'],)
                )
                
                report_data = {
                    'team': self.team_configs[user['team']].name,
                    'period': report_period,
                    'generated_at': datetime.now().isoformat(),
                    'members': []
                }
                
                for member_id, member_name in team_members:
                    metrics = self.calculate_productivity_metrics(member_id, report_period)
                    member_data = {
                        'name': member_name,
                        'metrics': metrics,
                        'insights': self.generate_insights(member_id) if include_insights else []
                    }
                    report_data['members'].append(member_data)
                
                # Display report
                st.markdown("### 📊 Team Performance Report")
                st.json(report_data)
                
                # Export options
                st.download_button(
                    "📤 Download JSON Report",
                    json.dumps(report_data, indent=2),
                    f"team_report_{user['team']}_{report_period}_{date.today()}.json",
                    "application/json"
                )
    
    def show_admin_panel(self, user: Dict):
        """Show admin panel"""
        if user['role'] != 'admin':
            st.error("Access denied. Admin privileges required.")
            return
        
        st.subheader("⚙️ Admin Panel")
        
        # System statistics
        st.markdown("### 📊 System Statistics")
        
        total_users = len(self.db.execute_query("SELECT id FROM users"))
        total_entries = len(self.db.execute_query("SELECT id FROM daily_entries"))
        active_today = len(self.db.execute_query(
            "SELECT DISTINCT user_id FROM daily_entries WHERE date = ?",
            (date.today().isoformat(),)
        ))
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            st.metric("👥 Total Users", total_users)
        with col2:
            st.metric("📝 Total Entries", total_entries)
        with col3:
            st.metric("✅ Active Today", active_today)
        
        # User management
        st.markdown("### 👥 User Management")
        
        all_users = self.db.execute_query("SELECT name, email, role, team, location_type FROM users")
        if all_users:
            users_df = pd.DataFrame(all_users, columns=['Name', 'Email', 'Role', 'Team', 'Location'])
            # Add expected hours column
            users_df['Expected Hours'] = users_df['Location'].apply(
                lambda x: '8.8h' if x == 'offshore' else '8.0h'
            )
            st.dataframe(users_df, use_container_width=True)

# Initialize and run the application
if __name__ == "__main__":
    app = ProductivityTracker()
    app.run()