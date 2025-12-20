var supabase = window.__supabaseClient || null;
var supabaseReady = false;

        function isSignupAllowed() {
            const setting = localStorage.getItem('auth_allow_signup_v1');
            if (setting == null) {
                localStorage.setItem('auth_allow_signup_v1', '1');
                return true;
            }
            return setting === '1';
        }

        function setAuthControlsEnabled(enabled) {
            const inputs = [
                document.getElementById('email'),
                document.getElementById('password'),
                document.getElementById('reset-email'),
                document.getElementById('new-password'),
                document.getElementById('confirm-password'),
            ];
            const buttons = [
                document.getElementById('login-btn'),
                document.getElementById('register-btn'),
                document.getElementById('send-reset-btn'),
                document.getElementById('update-password-btn'),
            ];
            for (const el of inputs) {
                if (el) el.disabled = !enabled;
            }
            for (const btn of buttons) {
                if (btn) btn.disabled = !enabled;
            }
        }

        function parseUrlParams() {
            const search = new URLSearchParams(String(window.location.search || ''));
            const rawHash = String(window.location.hash || '');
            const hash = rawHash.startsWith('#') ? rawHash.slice(1) : rawHash;
            const hashParams = new URLSearchParams(hash);
            return { search, hash: hashParams };
        }

        function configEndpoint(path) {
            const base = new URL('.', window.location.href);
            const cleaned = String(path || '').replace(/^\/+/, '');
            return new URL(cleaned, base).toString();
        }

        async function fetchConfig() {
            const candidates = ['config', 'api/config'];
            let lastError = null;
            for (const path of candidates) {
                try {
                    const res = await fetch(configEndpoint(path));
                    if (!res.ok) {
                        if (res.status === 404) {
                            lastError = new Error(`Config endpoint ${path} not found`);
                            continue;
                        }
                        throw new Error(await res.text());
                    }
                    return await res.json();
                } catch (e) {
                    lastError = e;
                }
            }
            throw lastError || new Error('Config fetch failed');
        }

        async function requireSupabaseLibrary() {
            if (window.supabase && typeof window.supabase.createClient === 'function') return;
            // Help debug the most common cause in Spaces: the bundle isn't being served.
            try {
                const url = configEndpoint('static/vendor/supabase-js.min.js');
                const res = await fetch(url, { method: 'GET' });
                if (!res.ok) {
                    throw new Error(`Supabase JS bundle missing (${res.status}) at ${url}`);
                }
                const text = await res.text();
                if (text.trimStart().startsWith('<')) {
                    throw new Error(`Supabase JS bundle URL returned HTML (likely 404 page): ${url}`);
                }
            } catch (e) {
                throw new Error(e?.message || String(e));
            }
            throw new Error('Supabase client library failed to load (bundle fetched but window.supabase is missing).');
        }

        function isRecoveryUrl() {
            const { search, hash } = parseUrlParams();
            const type = String(hash.get('type') || search.get('type') || '').toLowerCase();
            if (type === 'recovery') return true;
            // Some links carry the tokens but omit `type`.
            if (hash.get('access_token') || search.get('code')) return true;
            return false;
        }

        async function consumeSessionFromUrl() {
            if (!supabase) return { ok: false, isRecovery: false, error: null };
            const isRecovery = isRecoveryUrl();
            if (!isRecovery) return { ok: false, isRecovery: false, error: null };

            try {
                // Supabase links can be:
                // - hash tokens: #access_token=...&refresh_token=...&type=recovery
                // - PKCE code: ?code=...
                // getSessionFromUrl handles both and stores the session when storeSession=true.
                const { data, error } = await supabase.auth.getSessionFromUrl({ storeSession: true });
                if (error) return { ok: false, isRecovery: true, error };
                const hasSession = !!data?.session;
                if (hasSession) {
                    // Clean up URL to avoid leaking tokens via screenshots/logs/referrers.
                    try { history.replaceState({}, '', '/login#type=recovery'); } catch { }
                }
                return { ok: hasSession, isRecovery: true, error: null };
            } catch (e) {
                console.error('Failed to consume session from URL', e);
                return { ok: false, isRecovery: true, error: e };
            }
        }

        async function initSupabase() {
            try {
                setAuthControlsEnabled(false);
                const config = await fetchConfig();
                if (!config.supabase_url || !config.supabase_key) {
                    throw new Error('Supabase configuration missing (supabase_url/supabase_key).');
                }
                await requireSupabaseLibrary();
                supabase = window.__supabaseClient || window.supabase.createClient(config.supabase_url, config.supabase_key);
                window.__supabaseClient = supabase;
                supabaseReady = true;
                setAuthControlsEnabled(true);

                // Register toggle (defaults to allowed unless explicitly disabled).
                const allowSignup = isSignupAllowed();
                const registerBtn = document.getElementById('register-btn');
                if (!allowSignup && registerBtn) {
                    registerBtn.style.display = 'none';
                }

                const consumed = await consumeSessionFromUrl();

                supabase.auth.onAuthStateChange((event, session) => {
                    if (event === 'PASSWORD_RECOVERY') {
                        // Best-effort URL cleanup.
                        try { history.replaceState({}, '', '/login#type=recovery'); } catch { }
                        showUpdatePanel();
                        return;
                    }
                    const recovery = isRecoveryUrl();
                    if (session && !recovery) {
                        window.location.href = '/app';
                    }
                });

                const recovery = consumed.isRecovery || isRecoveryUrl();
                const { data: { session } } = await supabase.auth.getSession();
                if (session && !recovery) {
                    window.location.href = '/app';
                    return;
                }
                if (recovery) {
                    if (consumed.isRecovery && !consumed.ok && consumed.error) {
                        showAlert(
                            `Recovery link error: ${consumed.error?.message || String(consumed.error)}\n\n` +
                            `Fix: ensure Supabase Auth → URL Configuration includes ${window.location.origin}/login.`,
                        );
                    }
                    showUpdatePanel();
                } else {
                    showLoginPanel();
                }
            } catch (error) {
                console.error('Error initializing Supabase:', error);
                const msg = error?.message || String(error);
                showAlert(`Error initializing application configuration: ${msg}`, 'error');
                setAuthControlsEnabled(false);
            }
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

            if (!supabase || !supabaseReady) {
                showAlert('Supabase not initialized. Please refresh and try again.');
                return;
            }

            try {
                let result;
                if (type === 'login') {
                    result = await supabase.auth.signInWithPassword({ email, password });
                } else {
                    const redirect = `${window.location.origin}/login`;
                    result = await supabase.auth.signUp({ email, password, options: { emailRedirectTo: redirect } });
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
                await consumeSessionFromUrl();
                const { data: { session } } = await supabase.auth.getSession();
                if (!session) {
                    showAlert(
                        'Missing recovery session.\n\n' +
                        'Fix: open the password recovery email link again, and ensure Supabase Redirect URLs include /login.',
                    );
                    return;
                }
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
            if (isSignupAllowed()) {
                handleAuth('register');
            } else {
                showAlert('Registration is disabled by the administrator.');
            }
        });

        initSupabase();
