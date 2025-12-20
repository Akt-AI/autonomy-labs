let supabase;

        function parseHashParams() {
            const raw = String(window.location.hash || '');
            const s = raw.startsWith('#') ? raw.slice(1) : raw;
            try {
                return new URLSearchParams(s);
            } catch {
                return new URLSearchParams();
            }
        }

        async function consumeRecoverySessionFromUrl() {
            if (!supabase) return false;
            const params = parseHashParams();
            const type = String(params.get('type') || '').trim().toLowerCase();
            const access_token = String(params.get('access_token') || '').trim();
            const refresh_token = String(params.get('refresh_token') || '').trim();
            if (type !== 'recovery' || !access_token || !refresh_token) return false;

            try {
                const { error } = await supabase.auth.setSession({ access_token, refresh_token });
                if (error) throw error;
                // Clean up the URL to avoid leaking tokens via screenshots/logs.
                try { history.replaceState({}, '', '/login#type=recovery'); } catch { }
                return true;
            } catch (e) {
                console.error('Failed to set recovery session', e);
                return false;
            }
        }

        async function initSupabase() {
            try {
                const res = await fetch('/config');
                const config = await res.json();
                if (!config.supabase_url || !config.supabase_key) {
                    throw new Error('Supabase configuration missing');
                }
                supabase = window.supabase.createClient(config.supabase_url, config.supabase_key);

                // Register toggle (default disabled)
                const allowSignup = localStorage.getItem('auth_allow_signup_v1') === '1';
                const registerBtn = document.getElementById('register-btn');
                if (!allowSignup && registerBtn) {
                    registerBtn.style.display = 'none';
                }

                const recovered = await consumeRecoverySessionFromUrl();

                supabase.auth.onAuthStateChange((event, session) => {
                    if (event === 'PASSWORD_RECOVERY') {
                        showUpdatePanel();
                        return;
                    }
                    const recovery = isRecoveryUrl();
                    if (session && !recovery) {
                        window.location.href = '/app';
                    }
                });

                const recovery = recovered || isRecoveryUrl();
                const { data: { session } } = await supabase.auth.getSession();
                if (session && !recovery) {
                    window.location.href = '/app';
                    return;
                }
                if (recovery) {
                    showUpdatePanel();
                } else {
                    showLoginPanel();
                }
            } catch (error) {
                console.error('Error initializing Supabase:', error);
                showAlert('Error initializing application configuration', 'error');
            }
        }

        function isRecoveryUrl() {
            const hash = String(window.location.hash || '');
            const search = String(window.location.search || '');
            return hash.includes('type=recovery') || search.includes('type=recovery') || hash.includes('recovery');
        }

        function getPanels() {
            return {
                login: document.getElementById('auth-form'),
                reset: document.getElementById('reset-panel'),
                update: document.getElementById('update-panel'),
            };
        }

        function showLoginPanel() {
            const { login, reset, update } = getPanels();
            if (login) login.classList.remove('hidden');
            if (reset) reset.classList.add('hidden');
            if (update) update.classList.add('hidden');
        }

        function showResetPanel() {
            const { login, reset, update } = getPanels();
            if (login) login.classList.add('hidden');
            if (reset) reset.classList.remove('hidden');
            if (update) update.classList.add('hidden');

            const email = document.getElementById('email')?.value || '';
            const el = document.getElementById('reset-email');
            if (el && email) el.value = email;
        }

        function showUpdatePanel() {
            const { login, reset, update } = getPanels();
            if (login) login.classList.add('hidden');
            if (reset) reset.classList.add('hidden');
            if (update) update.classList.remove('hidden');
        }

        function showAlert(message, type = 'error') {
            const alert = document.getElementById('alert');
            alert.textContent = message;
            alert.classList.remove('hidden');
            if (type === 'success') {
                alert.classList.remove('text-red-500');
                alert.classList.add('text-green-500');
            } else {
                alert.classList.remove('text-green-500');
                alert.classList.add('text-red-500');
            }
        }

        async function handleAuth(type) {
            const email = document.getElementById('email').value;
            const password = document.getElementById('password').value;

            if (!supabase) {
                showAlert('Supabase not initialized');
                return;
            }

            try {
                let result;
                if (type === 'login') {
                    result = await supabase.auth.signInWithPassword({ email, password });
                } else {
                    result = await supabase.auth.signUp({ email, password });
                }

                if (result.error) throw result.error;

                if (type === 'register') {
                    if (result.data && result.data.session) {
                        // Email verification is disabled, user is logged in
                        window.location.href = '/app';
                    } else {
                        showAlert('Registration successful! Please check your email to verify (if enabled) or try logging in.', 'success');
                    }
                } else {
                    window.location.href = '/app';
                }
            } catch (error) {
                showAlert(error.message);
            }
        }

        document.getElementById('auth-form').addEventListener('submit', (e) => {
            e.preventDefault();
            handleAuth('login');
        });

        document.getElementById('forgot-btn').addEventListener('click', () => {
            showResetPanel();
        });

        document.getElementById('cancel-reset-btn').addEventListener('click', () => {
            showLoginPanel();
        });

        document.getElementById('send-reset-btn').addEventListener('click', async () => {
            const email = (document.getElementById('reset-email')?.value || '').trim();
            if (!email) {
                showAlert('Enter your email to receive a reset link.');
                return;
            }
            try {
                const redirectTo = `${window.location.origin}/login`;
                const { error } = await supabase.auth.resetPasswordForEmail(email, { redirectTo });
                if (error) throw error;
                showAlert('Reset link sent. Check your email.', 'success');
                showLoginPanel();
            } catch (e) {
                const msg = e?.message || String(e);
                if (String(msg).toLowerCase().includes('redirect')) {
                    showAlert(`${msg}\n\nFix: add ${window.location.origin}/login to Supabase Auth → URL Configuration → Redirect URLs.`);
                    return;
                }
                showAlert(msg);
            }
        });

        document.getElementById('cancel-update-btn').addEventListener('click', async () => {
            try { await supabase.auth.signOut(); } catch { }
            window.location.replace('/login');
        });

        document.getElementById('update-password-btn').addEventListener('click', async () => {
            const p1 = (document.getElementById('new-password')?.value || '').trim();
            const p2 = (document.getElementById('confirm-password')?.value || '').trim();
            if (!p1 || p1.length < 8) {
                showAlert('Password must be at least 8 characters.');
                return;
            }
            if (p1 !== p2) {
                showAlert('Passwords do not match.');
                return;
            }
            try {
                // Some deployments require explicitly consuming tokens from the recovery URL.
                await consumeRecoverySessionFromUrl();
                const { error } = await supabase.auth.updateUser({ password: p1 });
                if (error) throw error;
                showAlert('Password updated. You can log in now.', 'success');
                try { await supabase.auth.signOut(); } catch { }
                window.location.replace('/login');
            } catch (e) {
                showAlert(e?.message || String(e));
            }
        });

        document.getElementById('register-btn').addEventListener('click', () => {
            if (localStorage.getItem('auth_allow_signup_v1') === '1') {
                handleAuth('register');
            } else {
                showAlert('Registration is disabled by the administrator.');
            }
        });

        initSupabase();
