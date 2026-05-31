/**
 * myDailyAgent — Frontend Core Client Controller
 * Version 2.0
 * 
 * Manages SPA navigation, authentication state, reactive projects mapping,
 * team allocation roster, standup stopwatch meeting lifecycles with attendance logs,
 * and LangGraph multi-agent orchestration chat dispatches.
 */

document.addEventListener("DOMContentLoaded", () => {
    // ─── Constants & State ───
    const API_BASE = ""; // Relative paths since served from same origin

    let state = {
        token: localStorage.getItem("em_access_token") || null,
        username: localStorage.getItem("em_username") || null,
        role: localStorage.getItem("em_role") || null,
        userId: localStorage.getItem("em_user_id") || null,
        
        projects: [],
        activeProjectId: localStorage.getItem("em_active_project_id") || null,
        
        activeMeeting: null,
        stopwatchInterval: null,
        
        users: [] // Registered users list
    };

    // ─── DOM Element Selectors ───
    const dom = {
        // Navigation & Sidebar
        navBtns: document.querySelectorAll(".nav-btn"),
        tabContents: document.querySelectorAll(".tab-content"),
        statusUserName: document.getElementById("status-user-name"),
        statusUserRole: document.getElementById("status-user-role"),
        globalProjectSelect: document.getElementById("global-project-select"),
        sidebarJiraBadge: document.getElementById("sidebar-jira-badge"),
        sidebarJiraStatus: document.getElementById("sidebar-jira-status"),
        
        // Tab Auth
        loginForm: document.getElementById("login-form"),
        registerForm: document.getElementById("register-form"),
        loginUser: document.getElementById("login-username"),
        loginPass: document.getElementById("login-password"),
        regUser: document.getElementById("reg-username"),
        regEmail: document.getElementById("reg-email"),
        regFullName: document.getElementById("reg-fullname"),
        regPass: document.getElementById("reg-password"),
        
        // Tab Project Setup
        projectForm: document.getElementById("project-form"),
        projName: document.getElementById("proj-name"),
        projKey: document.getElementById("proj-key"),
        projJiraUrl: document.getElementById("proj-jira-url"),
        projJiraEmail: document.getElementById("proj-jira-email"),
        projJiraToken: document.getElementById("proj-jira-token"),
        projJiraKey: document.getElementById("proj-jira-key"),
        btnTestJira: document.getElementById("btn-test-jira"),
        projectJiraStatusText: document.getElementById("project-jira-status-text"),
        projSmtpServer: document.getElementById("proj-smtp-server"),
        projSmtpPort: document.getElementById("proj-smtp-port"),
        projSenderEmail: document.getElementById("proj-sender-email"),
        projSenderPassword: document.getElementById("proj-sender-password"),
        projRecipientEmails: document.getElementById("proj-recipient-emails"),
        projMeetingLink: document.getElementById("proj-meeting-link"),
        projConfProvider: document.getElementById("proj-conf-provider"),
        projMeetingLinkWrapper: document.getElementById("proj-meeting-link-wrapper"),
        projConfInfoBox: document.getElementById("proj-conf-info-box"),
        projStandupTime: document.getElementById("proj-standup-time"),
        projReminderTime: document.getElementById("proj-reminder-time"),
        projSprintDays: document.getElementById("proj-sprint-days"),
        
        // Tab Team
        rosterList: document.getElementById("roster-list"),
        teamAllocForm: document.getElementById("team-alloc-form"),
        allocUserId: document.getElementById("alloc-user-id"),
        allocRole: document.getElementById("alloc-role"),
        allocJiraUsername: document.getElementById("alloc-jira-username"),
        
        // Tab Meeting
        clockDisplay: document.getElementById("clock-display"),
        btnStartMeeting: document.getElementById("btn-start-meeting"),
        btnStopMeeting: document.getElementById("btn-stop-meeting"),
        activeMeetingSummary: document.getElementById("active-meeting-summary"),
        attendanceSheetList: document.getElementById("attendance-sheet-list"),
        
        // Tab Agent Chat
        chatTerminal: document.getElementById("chat-terminal"),
        chatInputField: document.getElementById("chat-input-field"),
        btnSendMessage: document.getElementById("btn-send-message"),
        logTimeline: document.getElementById("log-timeline"),

        // Tab PM Dashboard
        pmCompletedJira: document.getElementById("pm-completed-jira"),
        pmStalledIssues: document.getElementById("pm-stalled-issues"),
        pmTotalActiveIssues: document.getElementById("pm-total-active-issues"),
        pmSprintHealth: document.getElementById("pm-sprint-health"),
        pmStalledList: document.getElementById("pm-stalled-list"),
        pmAssignedList: document.getElementById("pm-assigned-list"),
        pmLeaderboard: document.getElementById("pm-leaderboard"),
        
        // Meeting Sync Banner
        pmMeetingSyncBanner: document.getElementById("pm-meeting-sync-banner"),
        pmMeetingSyncStatus: document.getElementById("pm-meeting-sync-status"),
        pmMeetingSyncIcon: document.getElementById("pm-meeting-sync-icon")
    };

    // ─── Helpers: Requests with Headers ───
    async function apiRequest(endpoint, options = {}) {
        const headers = {
            "Content-Type": "application/json",
            "Accept": "application/json"
        };
        if (state.token) {
            headers["Authorization"] = `Bearer ${state.token}`;
        }
        
        const config = {
            ...options,
            headers: {
                ...headers,
                ...options.headers
            }
        };

        try {
            const response = await fetch(endpoint, config);
            if (response.status === 401) {
                // Token expired or invalid, force logout
                logout();
                throw new Error("Session expired. Please log in again.");
            }
            if (response.status === 429) {
                throw new Error("Rate limit exceeded. Please try again later.");
            }
            if (!response.ok) {
                const errData = await response.json().catch(() => ({}));
                throw new Error(errData.detail || `Request failed with status ${response.status}`);
            }
            return await response.json();
        } catch (error) {
            console.error(`API Error on ${endpoint}:`, error);
            throw error;
        }
    }

    // Show floating alert notification
    function showAlert(message, type = "error") {
        const alertDiv = document.createElement("div");
        alertDiv.className = `alert-toast ${type}`;
        alertDiv.innerHTML = `
            <i class="fa-solid ${type === 'success' ? 'fa-circle-check' : 'fa-circle-exclamation'}"></i>
            <span>${message}</span>
        `;
        
        // Style alert toast dynamically
        Object.assign(alertDiv.style, {
            position: "fixed",
            bottom: "30px",
            right: "30px",
            backgroundColor: type === "success" ? "rgba(16, 185, 129, 0.95)" : "rgba(239, 68, 68, 0.95)",
            color: "#FFF",
            padding: "16px 24px",
            borderRadius: "12px",
            display: "flex",
            alignItems: "center",
            gap: "12px",
            boxShadow: "0 10px 25px rgba(0,0,0,0.3)",
            zIndex: "9999",
            backdropFilter: "blur(8px)",
            fontWeight: "500",
            fontSize: "14px",
            opacity: "0",
            transform: "translateY(20px)",
            transition: "all 0.3s cubic-bezier(0.4, 0, 0.2, 1)"
        });

        document.body.appendChild(alertDiv);
        
        // Trigger reflow & animation
        setTimeout(() => {
            alertDiv.style.opacity = "1";
            alertDiv.style.transform = "translateY(0)";
        }, 50);

        // Auto remove
        setTimeout(() => {
            alertDiv.style.opacity = "0";
            alertDiv.style.transform = "translateY(20px)";
            setTimeout(() => alertDiv.remove(), 300);
        }, 4000);
    }

    // ─── View Controller ───
    function initViews() {
        // Tab Switching Handler
        dom.navBtns.forEach(btn => {
            btn.addEventListener("click", () => {
                const targetTab = btn.getAttribute("data-tab");
                activateTab(targetTab);
            });
        });

        // Setup global project select listener
        dom.globalProjectSelect.addEventListener("change", (e) => {
            const val = e.target.value;
            if (val === "new") {
                state.activeProjectId = null;
                clearProjectForm();
                showAlert("Ready to create a new project. Enter configurations.", "success");
            } else if (val) {
                state.activeProjectId = parseInt(val);
                localStorage.setItem("em_active_project_id", state.activeProjectId);
                loadActiveProjectData();
            } else {
                state.activeProjectId = null;
                clearProjectForm();
            }
        });
    }

    function activateTab(tabId) {
        // Deactivate all
        dom.navBtns.forEach(b => b.classList.remove("active"));
        dom.tabContents.forEach(t => t.classList.remove("active"));

        // Activate matching
        const matchingBtn = document.querySelector(`.nav-btn[data-tab="${tabId}"]`);
        const matchingTab = document.getElementById(tabId);
        
        if (matchingBtn && matchingTab) {
            matchingBtn.classList.add("active");
            matchingTab.classList.add("active");
        }

        if (tabId === "pm-dashboard-tab") {
            loadPmDashboardData();
        }
    }

    // ─── Authentication Flow ───
    function initAuth() {
        // Login Submit
        dom.loginForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            try {
                const data = await apiRequest("/api/auth/login", {
                    method: "POST",
                    body: JSON.stringify({
                        username: dom.loginUser.value,
                        password: dom.loginPass.value
                    })
                });
                
                loginSuccess(data);
                showAlert(`Welcome back, ${data.username}!`, "success");
            } catch (err) {
                showAlert(err.message || "Failed to log in.");
            }
        });

        // Register Submit
        dom.registerForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            try {
                const data = await apiRequest("/api/auth/register", {
                    method: "POST",
                    body: JSON.stringify({
                        username: dom.regUser.value,
                        email: dom.regEmail.value,
                        password: dom.regPass.value,
                        full_name: dom.regFullName.value
                    })
                });

                // Auto login on successful registration
                loginSuccess(data);
                showAlert("Account registered and logged in successfully!", "success");
            } catch (err) {
                showAlert(err.message || "Failed to register.");
            }
        });
    }

    async function checkAuthSession() {
        if (!state.token) {
            updateAuthState(false);
            return;
        }

        try {
            // Verify current session
            const user = await apiRequest("/api/auth/me");
            state.username = user.username;
            state.role = user.role;
            state.userId = user.id;
            
            localStorage.setItem("em_username", user.username);
            localStorage.setItem("em_role", user.role);
            localStorage.setItem("em_user_id", user.id);
            
            updateAuthState(true);
            loadProjects();
            loadAllRegisteredUsers();
        } catch (err) {
            logout();
        }
    }

    function loginSuccess(data) {
        state.token = data.access_token;
        state.username = data.username;
        state.role = data.role;
        state.userId = data.user_id;

        localStorage.setItem("em_access_token", data.access_token);
        localStorage.setItem("em_username", data.username);
        localStorage.setItem("em_role", data.role);
        localStorage.setItem("em_user_id", data.user_id);

        updateAuthState(true);
        loadProjects();
        loadAllRegisteredUsers();
        activateTab("project-tab");
    }

    function logout() {
        state.token = null;
        state.username = null;
        state.role = null;
        state.userId = null;
        state.projects = [];
        state.activeProjectId = null;
        
        localStorage.removeItem("em_access_token");
        localStorage.removeItem("em_username");
        localStorage.removeItem("em_role");
        localStorage.removeItem("em_user_id");
        localStorage.removeItem("em_active_project_id");

        if (state.stopwatchInterval) {
            clearInterval(state.stopwatchInterval);
            state.stopwatchInterval = null;
        }

        updateAuthState(false);
        activateTab("auth-tab");
        showAlert("Logged out successfully.", "success");
    }

    function updateAuthState(isAuthenticated) {
        if (isAuthenticated) {
            dom.statusUserName.textContent = state.username;
            dom.statusUserRole.textContent = state.role;
            
            // Enable Sidebar Nav buttons
            dom.navBtns.forEach(btn => {
                btn.removeAttribute("disabled");
                btn.style.opacity = "1";
                btn.style.pointerEvents = "all";
            });
            
            // Convert unauthenticated card style to active
            const userCard = document.getElementById("user-status-card");
            if (userCard) {
                userCard.style.borderColor = "rgba(0, 242, 254, 0.2)";
                userCard.style.background = "linear-gradient(135deg, rgba(79, 70, 229, 0.05), rgba(0, 242, 254, 0.03))";
                
                // Add logout option on click
                userCard.title = "Click to Log Out";
                userCard.style.cursor = "pointer";
                userCard.onclick = () => {
                    if (confirm("Are you sure you want to log out?")) {
                        logout();
                    }
                };
            }
        } else {
            dom.statusUserName.textContent = "Guest Mode";
            dom.statusUserRole.textContent = "Unauthenticated";
            
            // Disable tabs except Auth
            dom.navBtns.forEach(btn => {
                if (btn.getAttribute("data-tab") !== "auth-tab") {
                    btn.setAttribute("disabled", "true");
                    btn.style.opacity = "0.4";
                    btn.style.pointerEvents = "none";
                }
            });

            const userCard = document.getElementById("user-status-card");
            if (userCard) {
                userCard.style.borderColor = "var(--glass-border)";
                userCard.style.background = "var(--glass-bg)";
                userCard.title = "";
                userCard.style.cursor = "default";
                userCard.onclick = null;
            }
        }
    }

    // ─── Projects Administration ───
    async function loadProjects() {
        try {
            const data = await apiRequest("/api/projects");
            state.projects = data;
            
            populateProjectSelector();
            
            if (state.projects.length > 0) {
                // If previous active project exists and is still valid, select it
                const matched = state.projects.find(p => p.id == state.activeProjectId);
                if (matched) {
                    dom.globalProjectSelect.value = state.activeProjectId;
                } else {
                    state.activeProjectId = state.projects[0].id;
                    localStorage.setItem("em_active_project_id", state.activeProjectId);
                    dom.globalProjectSelect.value = state.activeProjectId;
                }
                loadActiveProjectData();
            } else {
                state.activeProjectId = null;
                dom.globalProjectSelect.value = "";
                clearProjectForm();
            }
        } catch (err) {
            showAlert(err.message || "Failed to load projects.");
        }
    }

    function populateProjectSelector() {
        // Start fresh
        dom.globalProjectSelect.innerHTML = "";
        
        if (state.projects.length === 0) {
            dom.globalProjectSelect.innerHTML = `<option value="">-- No Projects Found --</option>`;
        } else {
            state.projects.forEach(p => {
                const opt = document.createElement("option");
                opt.value = p.id;
                opt.textContent = `${p.name} [${p.key}]`;
                dom.globalProjectSelect.appendChild(opt);
            });
        }
        
        // Always append "+ Create New Project..."
        const newOpt = document.createElement("option");
        newOpt.value = "new";
        newOpt.textContent = "+ Create New Project...";
        dom.globalProjectSelect.appendChild(newOpt);
    }

    async function checkJiraConnectionStatus(projectId) {
        if (!projectId) {
            dom.sidebarJiraBadge.style.display = "none";
            return;
        }

        dom.sidebarJiraBadge.style.display = "flex";
        dom.sidebarJiraStatus.textContent = "Checking...";
        dom.sidebarJiraStatus.className = "status-label";

        try {
            const data = await apiRequest(`/api/projects/${projectId}/jira/test-connection`);
            if (data.status === "connected") {
                dom.sidebarJiraStatus.textContent = "Connected";
                dom.sidebarJiraStatus.className = "status-label connected";
                dom.sidebarJiraStatus.title = data.detail || "";
            } else if (data.status === "not_configured") {
                dom.sidebarJiraStatus.textContent = "Simulating (Offline)";
                dom.sidebarJiraStatus.className = "status-label mocked";
                dom.sidebarJiraStatus.title = "Offline mock mode active. Configure settings to connect.";
            } else {
                dom.sidebarJiraStatus.textContent = "Failed";
                dom.sidebarJiraStatus.className = "status-label failed";
                dom.sidebarJiraStatus.title = data.detail || "Jira connection failed.";
            }
        } catch (err) {
            dom.sidebarJiraStatus.textContent = "Error";
            dom.sidebarJiraStatus.className = "status-label failed";
            dom.sidebarJiraStatus.title = err.message;
        }
    }

    async function loadActiveProjectData() {
        if (!state.activeProjectId) return;
        
        try {
            const project = await apiRequest(`/api/projects/${state.activeProjectId}`);
            
            // Map values to form
            dom.projName.value = project.name || "";
            dom.projKey.value = project.key || "";
            dom.projJiraUrl.value = project.jira_base_url || "";
            dom.projJiraEmail.value = project.jira_email || "";
            dom.projJiraToken.value = ""; // Don't pre-populate passwords
            dom.projJiraKey.value = project.jira_project_key || "";
            dom.projSmtpServer.value = project.smtp_server || "";
            dom.projSmtpPort.value = project.smtp_port || "";
            dom.projSenderEmail.value = project.sender_email || "";
            dom.projSenderPassword.value = ""; // Don't pre-populate passwords
            dom.projRecipientEmails.value = project.recipient_emails || "";
            dom.projMeetingLink.value = project.meeting_link || "";
            dom.projConfProvider.value = project.conference_provider || "manual";
            toggleConferenceProviderView(project.conference_provider || "manual");
            dom.projStandupTime.value = project.standup_time || "";
            dom.projReminderTime.value = project.reminder_time || "";
            dom.projSprintDays.value = project.sprint_duration_days || 14;

            // Load connection status badge
            checkJiraConnectionStatus(state.activeProjectId);

            if (project.jira_base_url && project.jira_email) {
                dom.btnTestJira.style.display = "inline-block";
                dom.projectJiraStatusText.textContent = "";
            } else {
                dom.btnTestJira.style.display = "none";
                dom.projectJiraStatusText.textContent = "Offline (Mocks Active)";
                dom.projectJiraStatusText.style.color = "#ffaa00";
            }

            // Load subcomponents
            loadTeamRoster();
            checkActiveMeeting();

            // Refresh PM Dashboard if currently active
            const pmTab = document.getElementById("pm-dashboard-tab");
            if (pmTab && pmTab.classList.contains("active")) {
                loadPmDashboardData();
            }
        } catch (err) {
            showAlert(err.message || "Failed to fetch project details.");
        }
    }

    function clearProjectForm() {
        dom.projectForm.reset();
        
        // Remove active components displays
        dom.rosterList.innerHTML = `
            <div class="no-data-placeholder">
                <i class="fa-solid fa-users-slash"></i>
                <p>Select or create a project to configure roster allocations.</p>
            </div>
        `;
        dom.attendanceSheetList.innerHTML = `
            <div class="no-data-placeholder">
                <i class="fa-solid fa-user-clock"></i>
                <p>Select a project to initiate standup controls.</p>
            </div>
        `;
        
        dom.clockDisplay.textContent = "00:00:00";
        dom.btnStartMeeting.disabled = true;
        dom.btnStopMeeting.disabled = true;

        dom.sidebarJiraBadge.style.display = "none";
        dom.btnTestJira.style.display = "none";
        dom.projectJiraStatusText.textContent = "";
        
        // Clear PM Dashboard metrics
        loadPmDashboardData();
    }

    function toggleConferenceProviderView(provider) {
        if (!dom.projMeetingLinkWrapper || !dom.projConfInfoBox) return;
        if (provider === "manual") {
            dom.projMeetingLinkWrapper.style.display = "block";
            dom.projConfInfoBox.style.display = "none";
        } else {
            dom.projMeetingLinkWrapper.style.display = "none";
            dom.projConfInfoBox.style.display = "block";
        }
    }

    function initProjectForm() {
        if (dom.projConfProvider) {
            dom.projConfProvider.addEventListener("change", (e) => {
                toggleConferenceProviderView(e.target.value);
            });
        }

        dom.projectForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            
            const payload = {
                name: dom.projName.value,
                key: dom.projKey.value.toUpperCase(),
                jira_base_url: dom.projJiraUrl.value || null,
                jira_email: dom.projJiraEmail.value || null,
                jira_project_key: dom.projJiraKey.value || null,
                smtp_server: dom.projSmtpServer.value || null,
                smtp_port: dom.projSmtpPort.value ? parseInt(dom.projSmtpPort.value) : null,
                sender_email: dom.projSenderEmail.value || null,
                recipient_emails: dom.projRecipientEmails.value || null,
                meeting_link: dom.projConfProvider.value === "manual" ? (dom.projMeetingLink.value || null) : null,
                conference_provider: dom.projConfProvider.value || "manual",
                standup_time: dom.projStandupTime.value || null,
                reminder_time: dom.projReminderTime.value || null,
                sprint_duration_days: parseInt(dom.projSprintDays.value) || 14
            };

            // Capture password tokens only if entered
            if (dom.projJiraToken.value) payload.jira_api_token = dom.projJiraToken.value;
            if (dom.projSenderPassword.value) payload.sender_password = dom.projSenderPassword.value;

            try {
                if (state.activeProjectId) {
                    // Update
                    const updated = await apiRequest(`/api/projects/${state.activeProjectId}`, {
                        method: "PUT",
                        body: JSON.stringify(payload)
                    });
                    showAlert("Project updated successfully!", "success");
                    loadProjects();
                } else {
                    // Create
                    const created = await apiRequest("/api/projects", {
                        method: "POST",
                        body: JSON.stringify(payload)
                    });
                    showAlert(`Project '${created.key}' created successfully!`, "success");
                    state.activeProjectId = created.id;
                    localStorage.setItem("em_active_project_id", created.id);
                    loadProjects();
                }
            } catch (err) {
                showAlert(err.message || "Failed to save project settings.");
            }
        });

        // Test Connection handler
        dom.btnTestJira.addEventListener("click", async () => {
            if (!state.activeProjectId) return;

            dom.projectJiraStatusText.textContent = "Testing...";
            dom.projectJiraStatusText.style.color = "var(--text-muted)";
            dom.btnTestJira.disabled = true;

            try {
                const data = await apiRequest(`/api/projects/${state.activeProjectId}/jira/test-connection`);
                if (data.status === "connected") {
                    dom.projectJiraStatusText.textContent = "🟢 Connected Successfully!";
                    dom.projectJiraStatusText.style.color = "var(--accent-teal)";
                    showAlert("Jira connection tested successfully!", "success");
                } else if (data.status === "not_configured") {
                    dom.projectJiraStatusText.textContent = "🟡 Simulating Offline (Mocks)";
                    dom.projectJiraStatusText.style.color = "#ffaa00";
                } else {
                    dom.projectJiraStatusText.textContent = "🔴 Connection Failed";
                    dom.projectJiraStatusText.style.color = "var(--accent-error)";
                    showAlert(`Jira connection failed: ${data.detail}`, "error");
                }
                // Sync the sidebar badge as well
                checkJiraConnectionStatus(state.activeProjectId);
            } catch (err) {
                dom.projectJiraStatusText.textContent = "🔴 Error Testing";
                dom.projectJiraStatusText.style.color = "var(--accent-error)";
                showAlert(`Error: ${err.message}`, "error");
            } finally {
                dom.btnTestJira.disabled = false;
            }
        });
    }

    // ─── Team Allocations ───
    async function loadTeamRoster() {
        if (!state.activeProjectId) return;

        try {
            const roster = await apiRequest(`/api/projects/${state.activeProjectId}/team`);
            dom.rosterList.innerHTML = "";

            if (roster.length === 0) {
                dom.rosterList.innerHTML = `
                    <div class="no-data-placeholder">
                        <i class="fa-solid fa-users-slash"></i>
                        <p>No team members allocated to this project yet.</p>
                    </div>
                `;
                return;
            }

            roster.forEach(member => {
                const card = document.createElement("div");
                card.className = "roster-card";
                card.innerHTML = `
                    <div class="roster-info">
                        <span class="role-badge">${member.role}</span>
                        <div>
                            <p class="status-name" style="font-size: 15px;">${member.full_name || member.username}</p>
                            <p style="font-size: 11px; color: var(--text-muted);">Email: ${member.email || 'N/A'} | Jira: ${member.jira_username || 'None'}</p>
                        </div>
                    </div>
                    <button class="del-member-btn" data-id="${member.id}" title="Remove Member"><i class="fa-solid fa-user-minus"></i></button>
                `;
                
                // Hook delete trigger
                card.querySelector(".del-member-btn").addEventListener("click", async (e) => {
                    if (confirm(`Remove ${member.username} from project allocations?`)) {
                        try {
                            await apiRequest(`/api/projects/${state.activeProjectId}/team/${member.id}`, {
                                method: "DELETE"
                            });
                            showAlert("Member removed from project team roster.", "success");
                            loadTeamRoster();
                        } catch (err) {
                            showAlert(err.message || "Failed to remove member.");
                        }
                    }
                });

                dom.rosterList.appendChild(card);
            });
        } catch (err) {
            dom.rosterList.innerHTML = `<p style="padding:20px;color:var(--accent-error);">Failed to load team roster.</p>`;
        }
    }

    // ─── PM Dashboard ───
    async function loadPmDashboardData() {
        if (!state.activeProjectId) {
            // No active project selected, clear values and show empty state
            dom.pmCompletedJira.textContent = "0";
            dom.pmStalledIssues.textContent = "0";
            dom.pmTotalActiveIssues.textContent = "0";
            dom.pmSprintHealth.textContent = "100%";
            dom.pmStalledList.innerHTML = `
                <tr>
                    <td colspan="5" class="table-empty" style="padding: 24px; text-align: center; color: var(--text-muted);">No stalled issues detected. Sprint is moving perfectly!</td>
                </tr>
            `;
            dom.pmAssignedList.innerHTML = `
                <tr>
                    <td colspan="5" class="table-empty" style="padding: 24px; text-align: center; color: var(--text-muted);">Roster mapping empty or connection sync pending.</td>
                </tr>
            `;
            dom.pmLeaderboard.innerHTML = `
                <div class="no-data-placeholder" style="padding: 40px 20px; text-align: center; color: var(--text-muted);">
                    <i class="fa-solid fa-award" style="font-size: 32px; color: #ffaa00; margin-bottom: 12px;"></i>
                    <p>Sync active sprint metrics to build developer rankings.</p>
                </div>
            `;
            return;
        }

        try {
            // Fetch PM dashboard data
            const data = await apiRequest(`/api/projects/${state.activeProjectId}/pm-dashboard`);

            // Populate top metrics counters
            dom.pmCompletedJira.textContent = data.completed_jira || 0;
            dom.pmStalledIssues.textContent = data.stalled_count || 0;
            dom.pmTotalActiveIssues.textContent = data.total_active_issues || 0;
            dom.pmSprintHealth.textContent = data.sprint_health || "100%";

            // Populate Stalled list
            dom.pmStalledList.innerHTML = "";
            if (!data.stalled_issues || data.stalled_issues.length === 0) {
                dom.pmStalledList.innerHTML = `
                    <tr>
                        <td colspan="5" class="table-empty" style="padding: 24px; text-align: center; color: var(--text-muted);">No stalled issues detected. Sprint is moving perfectly!</td>
                    </tr>
                `;
            } else {
                data.stalled_issues.forEach(issue => {
                    const tr = document.createElement("tr");
                    tr.style.borderBottom = "1px solid var(--glass-border)";
                    tr.innerHTML = `
                        <td style="padding: 12px; font-weight: 600; color: var(--accent-blue);">${escapeHtml(issue.key)}</td>
                        <td style="padding: 12px; color: var(--text-primary); font-weight: 500;">${escapeHtml(issue.summary)}</td>
                        <td style="padding: 12px;"><span class="badge badge-warning" style="background: rgba(245, 158, 11, 0.1); color: #F59E0B; padding: 4px 8px; border-radius: 6px; font-size: 11px; font-weight: 600;">${escapeHtml(issue.status)}</span></td>
                        <td style="padding: 12px; color: var(--accent-error); font-weight: 600;">${issue.days_stagnant} days</td>
                        <td style="padding: 12px; color: var(--text-muted);">${escapeHtml(issue.assignee)}</td>
                    `;
                    dom.pmStalledList.appendChild(tr);
                });
            }

            // Populate Overall Assigned Issues per person
            dom.pmAssignedList.innerHTML = "";
            if (!data.assigned_per_person || data.assigned_per_person.length === 0) {
                dom.pmAssignedList.innerHTML = `
                    <tr>
                        <td colspan="5" class="table-empty" style="padding: 24px; text-align: center; color: var(--text-muted);">Roster mapping empty or connection sync pending.</td>
                    </tr>
                `;
            } else {
                data.assigned_per_person.forEach(item => {
                    const tr = document.createElement("tr");
                    tr.style.borderBottom = "1px solid var(--glass-border)";
                    tr.innerHTML = `
                        <td style="padding: 12px; font-weight: 500; color: var(--text-primary);">${escapeHtml(item.assignee)}</td>
                        <td style="padding: 12px; text-align: center; color: var(--text-muted);">${item.to_do}</td>
                        <td style="padding: 12px; text-align: center; color: var(--accent-blue); font-weight: 500;">${item.in_progress}</td>
                        <td style="padding: 12px; text-align: center; color: var(--accent-teal); font-weight: 500;">${item.done}</td>
                        <td style="padding: 12px; text-align: center; font-weight: 700; color: var(--text-primary);">${item.total}</td>
                    `;
                    dom.pmAssignedList.appendChild(tr);
                });
            }

            // Populate Leaderboard
            dom.pmLeaderboard.innerHTML = "";
            if (!data.leaderboard || data.leaderboard.length === 0) {
                dom.pmLeaderboard.innerHTML = `
                    <div class="no-data-placeholder" style="padding: 40px 20px; text-align: center; color: var(--text-muted);">
                        <i class="fa-solid fa-award" style="font-size: 32px; color: #ffaa00; margin-bottom: 12px;"></i>
                        <p>Sync active sprint metrics to build developer rankings.</p>
                    </div>
                `;
            } else {
                data.leaderboard.forEach(item => {
                    let rankClass = "other";
                    if (item.rank === 1) rankClass = "first";
                    else if (item.rank === 2) rankClass = "second";
                    else if (item.rank === 3) rankClass = "third";

                    const div = document.createElement("div");
                    div.className = "leaderboard-row";
                    div.innerHTML = `
                        <div style="display: flex; align-items: center; gap: 12px;">
                            <div class="leaderboard-rank ${rankClass}">${item.rank}</div>
                            <div>
                                <div style="font-weight: 600; color: var(--text-primary); font-size: 14px;">${escapeHtml(item.assignee)}</div>
                                <div style="font-size: 11px; color: var(--accent-teal); font-weight: 600; margin-top: 2px;">${escapeHtml(item.badge)}</div>
                            </div>
                        </div>
                        <div style="text-align: right;">
                            <div style="font-weight: 700; color: var(--text-primary); font-size: 14px;">${item.completed} completed</div>
                            <div style="font-size: 11px; color: var(--text-muted); margin-top: 2px;">Score: ${item.score} pts</div>
                        </div>
                    `;
                    dom.pmLeaderboard.appendChild(div);
                });
            }
        } catch (err) {
            console.error("Failed to load PM Dashboard data:", err);
            showAlert("Failed to fetch sprint PM metrics. Ensure active Jira credentials are configured.", "error");
        }
    }

    function escapeHtml(str) {
        if (!str) return "";
        if (typeof str !== 'string') return String(str);
        return str
            .replace(/&/g, "&amp;")
            .replace(/</g, "&lt;")
            .replace(/>/g, "&gt;")
            .replace(/"/g, "&quot;")
            .replace(/'/g, "&#039;");
    }

    async function loadAllRegisteredUsers() {
        try {
            // We retrieve all users in database to populate Select User allocations options
            const data = await apiRequest("/api/users");
            state.users = data;
            
            // Populate select element
            dom.allocUserId.innerHTML = `<option value="">-- Choose User --</option>`;
            state.users.forEach(u => {
                const opt = document.createElement("option");
                opt.value = u.id;
                opt.textContent = `${u.full_name || u.username} (${u.role})`;
                dom.allocUserId.appendChild(opt);
            });
        } catch (err) {
            console.error("Failed to load global users list for allocation panel", err);
        }
    }

    function initTeamAllocation() {
        dom.teamAllocForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            
            if (!state.activeProjectId) {
                showAlert("Please select or configure a project first.");
                return;
            }

            const payload = {
                user_id: parseInt(dom.allocUserId.value),
                role: dom.allocRole.value,
                jira_username: dom.allocJiraUsername.value || null
            };

            try {
                await apiRequest(`/api/projects/${state.activeProjectId}/team`, {
                    method: "POST",
                    body: JSON.stringify(payload)
                });
                
                showAlert("Member allocated to project team successfully!", "success");
                dom.teamAllocForm.reset();
                loadTeamRoster();
            } catch (err) {
                showAlert(err.message || "Failed to allocate member.");
            }
        });
    }

    // ─── Meetings Clock & Lifecycle Control ───
    function updatePmMeetingSyncStatus(meetings) {
        if (!dom.pmMeetingSyncBanner || !dom.pmMeetingSyncStatus) return;

        // Filter and sort for scheduled meetings whose start time is in the future
        const now = new Date();
        const upcoming = meetings
            .filter(m => m.status === "scheduled" && new Date(m.scheduled_start) > now)
            .sort((a, b) => new Date(a.scheduled_start) - new Date(b.scheduled_start));

        if (upcoming.length > 0) {
            const nextMtg = upcoming[0];
            const startTime = new Date(nextMtg.scheduled_start);
            const diffMs = startTime - now;
            const diffMins = Math.ceil(diffMs / 60000);

            // Format dynamic readable countdown
            let timeStr = "";
            if (diffMins < 60) {
                timeStr = `${diffMins} min${diffMins > 1 ? 's' : ''}`;
            } else {
                const hours = Math.floor(diffMins / 60);
                const mins = diffMins % 60;
                timeStr = `${hours}h ${mins}m`;
            }

            // Update DOM with highlight ready status
            dom.pmMeetingSyncStatus.innerHTML = `Next meeting scheduled in <strong>${timeStr}</strong>. Agent is ready to join!`;
            dom.pmMeetingSyncBanner.style.border = "1px solid rgba(16, 185, 129, 0.4)";
            dom.pmMeetingSyncBanner.style.background = "rgba(16, 185, 129, 0.05)";
            dom.pmMeetingSyncBanner.style.color = "#10B981";

            if (dom.pmMeetingSyncIcon) {
                dom.pmMeetingSyncIcon.className = "fa-solid fa-clock-rotate-left fa-pulse";
                dom.pmMeetingSyncIcon.style.color = "#10B981";
            }
        } else {
            // Update DOM with neutral empty scheduled status
            dom.pmMeetingSyncStatus.textContent = "No active meeting scheduled.";
            dom.pmMeetingSyncBanner.style.border = "1px solid var(--glass-border)";
            dom.pmMeetingSyncBanner.style.background = "rgba(255, 255, 255, 0.02)";
            dom.pmMeetingSyncBanner.style.color = "var(--text-muted)";

            if (dom.pmMeetingSyncIcon) {
                dom.pmMeetingSyncIcon.className = "fa-solid fa-robot";
                dom.pmMeetingSyncIcon.style.color = "var(--accent-blue)";
            }
        }
    }

    async function checkActiveMeeting() {
        if (!state.activeProjectId) return;

        try {
            const meetings = await apiRequest(`/api/projects/${state.activeProjectId}/meetings`);
            
            // Update the dynamic sync countdown status banner
            updatePmMeetingSyncStatus(meetings);

            // Find active meeting in progress
            const active = meetings.find(m => m.status === "in_progress");
            if (active) {
                state.activeMeeting = active;
                dom.btnStartMeeting.disabled = true;
                dom.btnStopMeeting.disabled = false;
                
                dom.activeMeetingSummary.innerHTML = `
                    Status: <span class="badge-status active">Active Standup (ID: ${active.id})</span>
                `;
                
                startStopwatch(new Date(active.actual_start));
                loadAttendanceSheet(active.id);
            } else {
                state.activeMeeting = null;
                dom.btnStartMeeting.disabled = false;
                dom.btnStopMeeting.disabled = true;
                
                dom.activeMeetingSummary.innerHTML = `
                    Status: <span class="badge-status pending">No active standup</span>
                `;
                
                dom.clockDisplay.textContent = "00:00:00";
                if (state.stopwatchInterval) {
                    clearInterval(state.stopwatchInterval);
                    state.stopwatchInterval = null;
                }
                
                // Clear attendance sheet
                dom.attendanceSheetList.innerHTML = `
                    <div class="no-data-placeholder">
                        <i class="fa-solid fa-user-clock"></i>
                        <p>Start a standup meeting to log roster attendance.</p>
                    </div>
                `;
            }
        } catch (err) {
            console.error("Failed to check active meeting status", err);
        }
    }

    function startStopwatch(startTime) {
        if (state.stopwatchInterval) clearInterval(state.stopwatchInterval);
        
        function tick() {
            const diff = Date.now() - startTime.getTime();
            const hrs = Math.floor(diff / 3600000).toString().padStart(2, '0');
            const mins = Math.floor((diff % 3600000) / 60000).toString().padStart(2, '0');
            const secs = Math.floor((diff % 60000) / 1000).toString().padStart(2, '0');
            
            dom.clockDisplay.textContent = `${hrs}:${mins}:${secs}`;
        }
        
        tick(); // Immediate
        state.stopwatchInterval = setInterval(tick, 1000);
    }

    async function loadAttendanceSheet(meetingId) {
        try {
            const list = await apiRequest(`/api/meetings/${meetingId}/attendance`);
            dom.attendanceSheetList.innerHTML = "";

            if (list.length === 0) {
                dom.attendanceSheetList.innerHTML = `
                    <div class="no-data-placeholder">
                        <i class="fa-solid fa-clipboard-user"></i>
                        <p>Roster team is empty. Allocate members in Team Roster.</p>
                    </div>
                `;
                return;
            }

            list.forEach(record => {
                const row = document.createElement("div");
                row.className = "attendance-member-row";
                row.innerHTML = `
                    <span><strong>${record.full_name || record.username}</strong></span>
                    <div style="display:flex;align-items:center;gap:15px;">
                        <span style="font-size: 12px; color: var(--text-muted);">Attended:</span>
                        <input type="checkbox" class="attendance-checkbox" data-uid="${record.user_id}" ${record.attended ? 'checked' : ''}>
                    </div>
                `;

                // Add real-time event checkbox logging
                row.querySelector(".attendance-checkbox").addEventListener("change", async (e) => {
                    const checked = e.target.checked;
                    try {
                        await apiRequest(`/api/meetings/${meetingId}/attendance`, {
                            method: "POST",
                            body: JSON.stringify([{
                                user_id: record.user_id,
                                attended: checked
                            }])
                        });
                        showAlert(`Updated attendance status for ${record.username}`, "success");
                    } catch (err) {
                        showAlert(err.message || "Failed to update attendance.");
                        e.target.checked = !checked; // revert
                    }
                });

                dom.attendanceSheetList.appendChild(row);
            });
        } catch (err) {
            dom.attendanceSheetList.innerHTML = `<p style="color:var(--accent-error);">Failed to load attendance list.</p>`;
        }
    }

    function initMeetingControls() {
        dom.btnStartMeeting.addEventListener("click", async () => {
            if (!state.activeProjectId) {
                showAlert("Please select a project first.");
                return;
            }

            try {
                // 1. Create scheduled meeting instance
                const mtg = await apiRequest("/api/meetings", {
                    method: "POST",
                    body: JSON.stringify({
                        project_id: state.activeProjectId,
                        meeting_type: "standup",
                        scheduled_start: new Date().toISOString()
                    })
                });

                // 2. Start lifecycle clock
                const started = await apiRequest(`/api/meetings/${mtg.id}/start`, {
                    method: "POST"
                });

                showAlert("Standup meeting started successfully!", "success");
                checkActiveMeeting();
            } catch (err) {
                showAlert(err.message || "Failed to start meeting.");
            }
        });

        dom.btnStopMeeting.addEventListener("click", async () => {
            if (!state.activeMeeting) return;

            try {
                await apiRequest(`/api/meetings/${state.activeMeeting.id}/stop`, {
                    method: "POST"
                });
                
                showAlert("Standup meeting completed and stopped.", "success");
                checkActiveMeeting();
            } catch (err) {
                showAlert(err.message || "Failed to stop meeting.");
            }
        });
    }

    // ─── LangGraph Interactive Chat Terminal ───
    function initAgentChat() {
        dom.btnSendMessage.addEventListener("click", () => sendChatPrompt());
        dom.chatInputField.addEventListener("keydown", (e) => {
            if (e.key === "Enter") {
                sendChatPrompt();
            }
        });
    }

    async function sendChatPrompt() {
        const text = dom.chatInputField.value.trim();
        if (!text) return;
        
        if (!state.activeProjectId) {
            showAlert("Please select an active project before prompting the supervisor.");
            return;
        }

        // Render User Message
        appendChatMessage("user", text);
        dom.chatInputField.value = "";

        // Reset and animate graph orchestration tracker
        animateTrackerRunning();

        try {
            const res = await apiRequest(`/api/projects/${state.activeProjectId}/agent/chat`, {
                method: "POST",
                body: JSON.stringify({ message: text })
            });

            // Set tracker success
            animateTrackerComplete(res.completed_agents);

            // Render Supervisor Agent response
            appendChatMessage("agent", res.response || "No response received from agent.");
        } catch (err) {
            showAlert(err.message || "Orchestration failed.");
            animateTrackerError(err.message);
        }
    }

    function appendChatMessage(sender, content) {
        const messageDiv = document.createElement("div");
        messageDiv.className = sender === "user" ? "user-message" : "agent-message";
        
        const avatarHTML = sender === "user" 
            ? `<div class="user-avatar-icon"><i class="fa-solid fa-user-tie"></i></div>`
            : `<div class="system-bot-icon"><i class="fa-solid fa-brain"></i></div>`;
            
        const bubbleClass = sender === "user" ? "user-bubble" : "agent-bubble";
        
        // Simple markdown parsing for bullets & tables in supervisor insights
        let parsedContent = content
            .replace(/\n/g, "<br>")
            .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
            .replace(/`([^`]+)`/g, "<code>$1</code>");

        messageDiv.innerHTML = `
            ${avatarHTML}
            <div class="${bubbleClass}">
                <p><strong>${sender === 'user' ? 'Manager Alice' : 'Engineering Manager Supervisor'}</strong></p>
                <p style="margin-top:8px;">${parsedContent}</p>
            </div>
        `;

        dom.chatTerminal.appendChild(messageDiv);
        
        // Scroll terminal to bottom
        dom.chatTerminal.scrollTop = dom.chatTerminal.scrollHeight;
    }

    // Graph Orchestration Animation Helpers
    function animateTrackerRunning() {
        dom.logTimeline.innerHTML = `
            <div class="log-item active">
                <span class="dot"></span>
                <span class="text">Supervisor matching task rules...</span>
            </div>
            <div class="log-item">
                <span class="dot"></span>
                <span class="text">Consulting LangGraph state maps...</span>
            </div>
            <div class="log-item">
                <span class="dot"></span>
                <span class="text">Querying Jira sprint backlogs...</span>
            </div>
            <div class="log-item">
                <span class="dot"></span>
                <span class="text">Formatting EM Standup Analytics...</span>
            </div>
        `;
        
        // Delay sequential step animations
        const items = dom.logTimeline.querySelectorAll(".log-item");
        setTimeout(() => {
            items[0].className = "log-item complete";
            items[1].className = "log-item active";
        }, 1500);

        setTimeout(() => {
            items[1].className = "log-item complete";
            items[2].className = "log-item active";
        }, 3000);

        setTimeout(() => {
            items[2].className = "log-item complete";
            items[3].className = "log-item active";
        }, 4500);
    }

    function animateTrackerComplete(completedAgents = []) {
        let finalTimelineHTML = "";
        
        // Render each step as complete
        const steps = [
            "Supervisor Matched Prompt Requirements",
            "StateGraph Nodes Orchestration Init",
            "Jira Cloud Board Synced Successfully",
            "Calculated Employee Productivity Scores",
            "Created Email Standup Summary Report"
        ];

        steps.forEach(step => {
            finalTimelineHTML += `
                <div class="log-item complete">
                    <span class="dot"></span>
                    <span class="text">${step}</span>
                </div>
            `;
        });

        // Append completed agents list if returned
        if (completedAgents && completedAgents.length > 0) {
            finalTimelineHTML += `
                <div class="log-item complete" style="color: var(--accent-teal);">
                    <span class="dot" style="background-color:var(--accent-teal);"></span>
                    <span class="text">Completed Agents: ${completedAgents.join(", ")}</span>
                </div>
            `;
        }

        dom.logTimeline.innerHTML = finalTimelineHTML;
    }

    function animateTrackerError(errText) {
        dom.logTimeline.innerHTML = `
            <div class="log-item complete">
                <span class="dot"></span>
                <span class="text">Orchestration Init</span>
            </div>
            <div class="log-item" style="color: var(--accent-error);">
                <span class="dot" style="background-color: var(--accent-error);"></span>
                <span class="text"><strong>Error:</strong> ${errText}</span>
            </div>
        `;
    }

    // ─── Initializer Chain ───
    initViews();
    initAuth();
    initProjectForm();
    initTeamAllocation();
    initMeetingControls();
    initAgentChat();
    
    // Validate current cookie/session tokens
    checkAuthSession();
});
