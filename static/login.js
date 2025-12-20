let supabase;

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

                // Check if already logged in
                const { data: { session } } = await supabase.auth.getSession();
                if (session) {
                    window.location.href = '/app';
                }
            } catch (error) {
                console.error('Error initializing Supabase:', error);
                showAlert('Error initializing application configuration', 'error');
            }
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

        document.getElementById('register-btn').addEventListener('click', () => {
            if (localStorage.getItem('auth_allow_signup_v1') === '1') {
                handleAuth('register');
            } else {
                showAlert('Registration is disabled by the administrator.');
            }
        });

        initSupabase();
