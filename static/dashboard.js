let supabase;
        // --- Multi-Terminal Logic ---
        let terminals = {}; // { id: { term, fitAddon, ws, containerId, scope } }
        let activeTerminalId = null; // scope: 'main'
        let activeAgentTerminalId = null; // scope: 'agent'
        let terminalCount = 0;

        const DOMPURIFY_CONFIG = {
            USE_PROFILES: { html: true, svg: true, mathMl: true },
            ADD_ATTR: ['data-language', 'data-lang', 'class', 'style']
        };

        function sanitizeHtml(html) {
            if (!window.DOMPurify) return html;
            return window.DOMPurify.sanitize(html, DOMPURIFY_CONFIG);
        }

        function preprocessMathDelimiters(text) {
            if (!text) return text;
            const withStandardDelimiters = text
                .replace(/\\\[/g, '$$')
                .replace(/\\\]/g, '$$')
                .replace(/\\\(/g, '$')
                .replace(/\\\)/g, '$');

            // Many LLMs emit LaTeX with double-escaped backslashes (e.g. "\\frac").
            // KaTeX expects single backslashes inside math, so normalize inside $...$ / $$...$$
            // while leaving code fences/inline code untouched.
            return normalizeMathBackslashes(withStandardDelimiters);
        }

        function normalizeMathBackslashes(markdown) {
            if (!markdown) return markdown;

            const parts = [];
            const fenceRe = /```[\s\S]*?```/g;
            let last = 0;
            let m;
            while ((m = fenceRe.exec(markdown)) !== null) {
                if (m.index > last) parts.push({ type: 'text', value: markdown.slice(last, m.index) });
                parts.push({ type: 'codefence', value: m[0] });
                last = m.index + m[0].length;
            }
            if (last < markdown.length) parts.push({ type: 'text', value: markdown.slice(last) });

            return parts
                .map((part) => {
                    if (part.type !== 'text') return part.value;

                    // Protect inline code spans.
                    const segments = [];
                    const inlineCodeRe = /`[^`]*`/g;
                    let lastSeg = 0;
                    let mi;
                    while ((mi = inlineCodeRe.exec(part.value)) !== null) {
                        if (mi.index > lastSeg) segments.push({ type: 'text', value: part.value.slice(lastSeg, mi.index) });
                        segments.push({ type: 'inlinecode', value: mi[0] });
                        lastSeg = mi.index + mi[0].length;
                    }
                    if (lastSeg < part.value.length) segments.push({ type: 'text', value: part.value.slice(lastSeg) });

                    const fixInner = (inner) => inner.replace(/\\\\(?=[a-zA-Z\\{}_^])/g, '\\');

                    return segments
                        .map((seg) => {
                            if (seg.type !== 'text') return seg.value;

                            // Block math
                            let out = seg.value.replace(/\$\$([\s\S]*?)\$\$/g, (_, inner) => `$$${fixInner(inner)}$$`);

                            // Inline math (best-effort; only normalizes sequences that look like LaTeX commands)
                            out = out.replace(/\$([^\n$]+?)\$/g, (_, inner) => {
                                if (!/\\\\(?=[a-zA-Z\\{}_^])/.test(inner)) return `$${inner}$`;
                                return `$${fixInner(inner)}$`;
                            });

                            return out;
                        })
                        .join('');
                })
                .join('');
        }

        function renderMathInMessage(containerEl) {
            if (!containerEl || typeof renderMathInElement !== 'function') return;
            try {
                renderMathInElement(containerEl, {
                    delimiters: [
                        { left: '$$', right: '$$', display: true },
                        { left: '$', right: '$', display: false }
                    ],
                    throwOnError: false
                });
            } catch (e) {
                console.log('KaTeX render error:', e);
            }
        }

        function renderMarkdownInto(containerEl, markdown) {
            const normalized = preprocessMathDelimiters(markdown || '');
            const html = marked.parse(normalized);
            containerEl.innerHTML = sanitizeHtml(html);
            containerEl.querySelectorAll('pre code').forEach((block) => {
                try { hljs.highlightElement(block); } catch { }
            });
            renderMathInMessage(containerEl);
            wireMessageCodeActions(containerEl);
        }

        function wireMessageCodeActions(containerEl) {
            containerEl.querySelectorAll('pre').forEach((pre) => {
                if (pre.querySelector('.copy-btn')) return;
                const codeEl = pre.querySelector('code');
                if (!codeEl) return;

                const copyBtn = document.createElement('button');
                copyBtn.className = 'copy-btn';
                copyBtn.type = 'button';
                copyBtn.textContent = 'Copy';
                copyBtn.onclick = async () => {
                    try {
                        await navigator.clipboard.writeText(codeEl.innerText);
                        copyBtn.textContent = 'Copied';
                        setTimeout(() => (copyBtn.textContent = 'Copy'), 800);
                    } catch { }
                };

                const runBtn = document.createElement('button');
                runBtn.className = 'run-btn';
                runBtn.type = 'button';
                runBtn.textContent = 'Run';
                runBtn.onclick = async () => {
                    const cmd = codeEl.innerText.replace(/\n+$/, '');
                    if (!cmd) return;
                    const agentVisible = !document.getElementById('chat-view').classList.contains('hidden')
                        && !document.getElementById('chat-autonomous').classList.contains('hidden');
                    await runInTerminal(cmd + '\n', { preferScope: agentVisible ? 'agent' : 'main', autoShow: true });
                };

                pre.appendChild(copyBtn);
                pre.appendChild(runBtn);
            });
        }

        async function runInTerminal(data, { preferScope = 'main', autoShow = false } = {}) {
            const desiredId = preferScope === 'agent' ? activeAgentTerminalId : activeTerminalId;
            if (!desiredId || !terminals[desiredId] || terminals[desiredId].ws.readyState !== WebSocket.OPEN) {
                const newId = createTerminalTab({ scope: preferScope });
                if (preferScope === 'agent') activeAgentTerminalId = newId;
                else activeTerminalId = newId;
            }
            const id = preferScope === 'agent' ? activeAgentTerminalId : activeTerminalId;
            const t = terminals[id];
            if (autoShow) {
                if (preferScope === 'agent') {
                    openAutonomousMode();
                    ensureAgentTerminalVisible();
                } else {
                    switchMode('terminal');
                }
            }
            if (t && t.ws && t.ws.readyState === WebSocket.OPEN) t.ws.send(data);
        }

        function ensureAgentTerminalVisible() {
            const paneTerminal = document.getElementById('agent-pane-terminal');
            if (paneTerminal && paneTerminal.classList.contains('hidden')) toggleAgentTerminalCollapsed();
        }

        function openSettings() {
            const overlay = document.getElementById('settings-overlay');
            const drawer = document.getElementById('settings-drawer');
            if (!overlay || !drawer) return;
            overlay.classList.remove('settings-hidden');
            drawer.classList.remove('settings-hidden');
            const signupToggle = document.getElementById('auth-allow-signup');
            if (signupToggle) signupToggle.checked = getAllowSignup();
        }

        function openAdmin() {
            openSettings();
            const admin = document.getElementById('admin-panel');
            if (admin) admin.scrollIntoView({ block: 'nearest' });
            // Best-effort auto-load templates for admins.
            setTimeout(() => loadAdminMcpTemplates(), 0);
        }

        function closeSettings() {
            const overlay = document.getElementById('settings-overlay');
            const drawer = document.getElementById('settings-drawer');
            if (!overlay || !drawer) return;
            overlay.classList.add('settings-hidden');
            drawer.classList.add('settings-hidden');
        }

        function toggleSettings() {
            const drawer = document.getElementById('settings-drawer');
            if (!drawer) return;
            const isHidden = drawer.classList.contains('settings-hidden');
            if (isHidden) openSettings();
            else closeSettings();
        }

        function applyTheme(theme) {
            const t = theme === 'light' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', t);
            localStorage.setItem('theme_v1', t);
            const icon = document.getElementById('theme-icon');
            if (icon) icon.textContent = t === 'light' ? '☀' : '☾';

            // Notes preview should not use prose-invert in light mode (it can make text appear missing).
            const notesPreview = document.getElementById('notes-preview');
            if (notesPreview) {
                notesPreview.classList.toggle('prose-invert', t !== 'light');
            }
        }

        function toggleTheme() {
            const current = localStorage.getItem('theme_v1') || 'dark';
            applyTheme(current === 'dark' ? 'light' : 'dark');
        }

        function toggleChatSidebar(forceOpen = null) {
            const sidebar = document.getElementById('chat-sidebar');
            if (!sidebar) return;
            const key = 'chat_sidebar_collapsed_v1';

            const isDesktop = window.matchMedia && window.matchMedia('(min-width: 768px)').matches;
            if (isDesktop) {
                const currentlyCollapsed = sidebar.classList.contains('md:hidden');
                const nextCollapsed = typeof forceOpen === 'boolean' ? !forceOpen : !currentlyCollapsed;
                sidebar.classList.toggle('md:hidden', nextCollapsed);
                localStorage.setItem(key, nextCollapsed ? '1' : '0');
            } else {
                const currentlyHidden = sidebar.classList.contains('hidden');
                const nextHidden = typeof forceOpen === 'boolean' ? !forceOpen : !currentlyHidden;
                sidebar.classList.toggle('hidden', nextHidden);
                // don't overwrite desktop preference on mobile toggle
            }
        }

        function getAllowSignup() {
            return localStorage.getItem('auth_allow_signup_v1') === '1';
        }

        function setAllowSignup(allowed) {
            localStorage.setItem('auth_allow_signup_v1', allowed ? '1' : '0');
            const el = document.getElementById('auth-allow-signup');
            if (el) el.checked = !!allowed;
        }

        function getCodexSdkSettings() {
            return {
                baseUrl: localStorage.getItem('codex_sdk_base_url_v1') || '',
                apiKey: localStorage.getItem('codex_sdk_api_key_v1') || '',
                model: localStorage.getItem('codex_sdk_model_v1') || '',
            };
        }

        function getCodexShowJsonl() {
            return localStorage.getItem('codex_show_jsonl_v1') === '1';
        }

        function setCodexShowJsonl(enabled) {
            localStorage.setItem('codex_show_jsonl_v1', enabled ? '1' : '0');
            const el = document.getElementById('codex-show-jsonl');
            if (el) el.checked = !!enabled;
        }

        function saveCodexSdkSettings() {
            const baseUrl = document.getElementById('codex-base-url')?.value || '';
            const apiKey = document.getElementById('codex-api-key')?.value || '';
            const model = document.getElementById('codex-model')?.value || '';
            localStorage.setItem('codex_sdk_base_url_v1', baseUrl.trim());
            localStorage.setItem('codex_sdk_api_key_v1', apiKey);
            localStorage.setItem('codex_sdk_model_v1', model.trim());
        }

        function getCodexSandboxMode() {
            return localStorage.getItem('codex_sandbox_mode_v1') || 'danger-full-access';
        }

        function saveCodexSandboxMode() {
            const mode = document.getElementById('codex-sandbox-mode')?.value || 'danger-full-access';
            localStorage.setItem('codex_sandbox_mode_v1', mode);
        }

        function getCodexWorkdir() {
            return localStorage.getItem('codex_workdir_v1') || '';
        }

        function saveCodexWorkdir() {
            const dir = document.getElementById('codex-workdir')?.value || '';
            localStorage.setItem('codex_workdir_v1', dir.trim());
        }

        function getAgentUseCodexCli() {
            return localStorage.getItem('agent_use_codex_cli_v1') === '1';
        }

        function setAgentUseCodexCli(enabled) {
            localStorage.setItem('agent_use_codex_cli_v1', enabled ? '1' : '0');
            const el = document.getElementById('agent-use-codex-cli');
            if (el) el.checked = !!enabled;
        }

        async function getAccessToken() {
            const direct = (window.__sbAccessToken || '').trim();
            if (direct) return direct;
            try {
                const { data: { session } } = await supabase.auth.getSession();
                const tok = (session?.access_token || '').trim();
                if (tok) window.__sbAccessToken = tok;
                return tok;
            } catch {
                return '';
            }
        }

        async function authFetch(url, options = {}) {
            const token = await getAccessToken();
            const headers = new Headers(options.headers || {});
            if (token && !headers.has('Authorization')) headers.set('Authorization', `Bearer ${token}`);
            return fetch(url, { ...options, headers });
        }

        async function loadMe() {
            try {
                const res = await authFetch('/api/me');
                if (!res.ok) return null;
                return await res.json();
            } catch {
                return null;
            }
        }

        function applyAdminUi(me) {
            const navBtn = document.getElementById('nav-admin');
            const mobileBtn = document.getElementById('mobile-admin');
            const panel = document.getElementById('admin-panel');
            const status = document.getElementById('admin-status');
            const features = document.getElementById('admin-features');

            const isAdmin = !!me?.isAdmin;
            if (navBtn) navBtn.classList.toggle('hidden', !isAdmin);
            if (mobileBtn) mobileBtn.classList.toggle('hidden', !isAdmin);
            if (panel) panel.classList.toggle('hidden', !isAdmin);
            if (!isAdmin) return;

            if (status) status.textContent = `Admin: ${me?.email || me?.id || 'unknown'}`;
            if (features) {
                const f = me?.features || {};
                features.innerHTML = [
                    `<div class=\"bg-gray-800/40 border border-gray-700 rounded-lg px-3 py-2\">terminal: <span class=\"text-gray-100\">${f.terminal ? 'on' : 'off'}</span></div>`,
                    `<div class=\"bg-gray-800/40 border border-gray-700 rounded-lg px-3 py-2\">codex: <span class=\"text-gray-100\">${f.codex ? 'on' : 'off'}</span></div>`,
                    `<div class=\"bg-gray-800/40 border border-gray-700 rounded-lg px-3 py-2\">mcp: <span class=\"text-gray-100\">${f.mcp ? 'on' : 'off'}</span></div>`,
                    `<div class=\"bg-gray-800/40 border border-gray-700 rounded-lg px-3 py-2\">indexing: <span class=\"text-gray-100\">${f.indexing ? 'on' : 'off'}</span></div>`,
                ].join('');
            }
        }

        function applyIndexingUi(me) {
            const enabled = !!me?.features?.indexing;
            const disabled = document.getElementById('rag-disabled');
            const controls = document.getElementById('rag-controls');
            const status = document.getElementById('rag-status');
            if (disabled) disabled.classList.toggle('hidden', enabled);
            if (controls) controls.classList.toggle('hidden', !enabled);
            if (status && !enabled) status.textContent = 'Enable indexing with ENABLE_INDEXING=1 and restart.';
        }

        function setRagStatus(text) {
            const el = document.getElementById('rag-status');
            if (el) el.textContent = text || '';
        }

        function renderRagDocuments(docs) {
            const el = document.getElementById('rag-documents');
            if (!el) return;
            el.innerHTML = '';

            const list = Array.isArray(docs) ? docs : [];
            if (!list.length) {
                const empty = document.createElement('div');
                empty.className = 'text-xs text-gray-500';
                empty.textContent = 'No documents yet.';
                el.appendChild(empty);
                return;
            }

            for (const d of list) {
                const row = document.createElement('div');
                row.className = 'flex items-center justify-between gap-2 bg-gray-800/40 border border-gray-700 rounded-lg px-3 py-2';

                const left = document.createElement('div');
                left.className = 'min-w-0';
                const name = document.createElement('div');
                name.className = 'text-sm text-gray-100 truncate';
                name.textContent = d?.name || d?.id || 'document';
                const meta = document.createElement('div');
                meta.className = 'text-xs text-gray-500';
                const bytes = typeof d?.bytes === 'number' ? d.bytes : 0;
                const chunks = typeof d?.chunks === 'number' ? d.chunks : 0;
                meta.textContent = `${bytes} bytes • ${chunks} chunks`;
                left.appendChild(name);
                left.appendChild(meta);

                const btn = document.createElement('button');
                btn.className = 'bg-red-600 hover:bg-red-700 text-white px-2 py-1 rounded text-xs shrink-0';
                btn.textContent = 'Delete';
                btn.onclick = () => deleteRagDocument(String(d?.id || ''));

                row.appendChild(left);
                row.appendChild(btn);
                el.appendChild(row);
            }
        }

        function renderRagResults(results) {
            const el = document.getElementById('rag-search-results');
            if (!el) return;
            el.innerHTML = '';

            const list = Array.isArray(results) ? results : [];
            if (!list.length) {
                const empty = document.createElement('div');
                empty.className = 'text-xs text-gray-500';
                empty.textContent = 'No results.';
                el.appendChild(empty);
                return;
            }

            for (const r of list) {
                const card = document.createElement('div');
                card.className = 'bg-gray-800/40 border border-gray-700 rounded-lg px-3 py-2';

                const title = document.createElement('div');
                title.className = 'text-xs text-gray-400';
                const score = r?.score ?? 0;
                const docName = r?.document?.name || r?.document?.id || 'document';
                title.textContent = `score ${score} • ${docName}`;

                const excerpt = document.createElement('div');
                excerpt.className = 'text-sm text-gray-100 whitespace-pre-wrap mt-1';
                excerpt.textContent = r?.excerpt || '';

                card.appendChild(title);
                card.appendChild(excerpt);
                el.appendChild(card);
            }
        }

        async function loadRagDocuments() {
            try {
                setRagStatus('Loading documents...');
                const res = await authFetch('/api/rag/documents');
                if (!res.ok) throw new Error(await res.text());
                const data = await res.json();
                renderRagDocuments(data?.documents || []);
                setRagStatus(`Loaded ${Array.isArray(data?.documents) ? data.documents.length : 0} document(s).`);
            } catch (e) {
                setRagStatus(`Failed to load documents: ${e?.message || e}`);
            }
        }

        async function uploadRagDocument() {
            const input = document.getElementById('rag-file-input');
            const file = input?.files?.[0];
            if (!file) {
                setRagStatus('Pick a file to upload.');
                return;
            }
            try {
                setRagStatus('Uploading...');
                const fd = new FormData();
                fd.append('file', file, file.name);
                const res = await authFetch('/api/rag/documents/upload', { method: 'POST', body: fd });
                if (!res.ok) throw new Error(await res.text());
                await res.json();
                if (input) input.value = '';
                await loadRagDocuments();
                setRagStatus('Upload complete.');
            } catch (e) {
                setRagStatus(`Upload failed: ${e?.message || e}`);
            }
        }

        async function deleteRagDocument(docId) {
            const id = (docId || '').trim();
            if (!id) return;
            if (!confirm('Delete this document?')) return;
            try {
                setRagStatus('Deleting...');
                const res = await authFetch(`/api/rag/documents/${encodeURIComponent(id)}`, { method: 'DELETE' });
                if (!res.ok) throw new Error(await res.text());
                await res.json();
                await loadRagDocuments();
                setRagStatus('Deleted.');
            } catch (e) {
                setRagStatus(`Delete failed: ${e?.message || e}`);
            }
        }

        async function searchRag() {
            const q = (document.getElementById('rag-query')?.value || '').trim();
            if (!q) {
                setRagStatus('Enter a query.');
                renderRagResults([]);
                return;
            }
            try {
                setRagStatus('Searching...');
                const res = await authFetch('/api/rag/search', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ query: q, limit: 8 }),
                });
                if (!res.ok) throw new Error(await res.text());
                const data = await res.json();
                renderRagResults(data?.results || []);
                setRagStatus(`Found ${Array.isArray(data?.results) ? data.results.length : 0} result(s).`);
            } catch (e) {
                setRagStatus(`Search failed: ${e?.message || e}`);
            }
        }

        async function loadAdminMcpTemplates() {
            const ta = document.getElementById('admin-mcp-templates');
            if (!ta) return;
            try {
                const res = await authFetch('/api/admin/mcp-templates');
                if (!res.ok) throw new Error(await res.text());
                const data = await res.json();
                ta.value = JSON.stringify(data, null, 2);
            } catch (e) {
                // Non-admins will get 403; don't spam.
                if (String(e?.message || e).includes('403')) return;
                console.warn('Failed to load MCP templates', e);
            }
        }

        async function saveAdminMcpTemplates() {
            const ta = document.getElementById('admin-mcp-templates');
            if (!ta) return;
            try {
                const parsed = JSON.parse(ta.value || '{}');
                const res = await authFetch('/api/admin/mcp-templates', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(parsed),
                });
                if (!res.ok) throw new Error(await res.text());
                const data = await res.json();
                alert(`Saved templates (${data?.count ?? 0})`);
            } catch (e) {
                alert(`Failed to save templates: ${e?.message || e}`);
            }
        }

        async function refreshCodexMcpServers() {
            const out = document.getElementById('codex-mcp-list');
            if (out) out.textContent = 'Loading...';
            try {
                const res = await authFetch('/api/codex/mcp');
                const data = await res.json();
                const names = Array.isArray(data?.servers) ? data.servers : [];
                if (out) out.textContent = names.length ? `Configured: ${names.join(', ')}` : 'No MCP servers configured.';
            } catch (e) {
                if (out) out.textContent = `Failed to list MCP servers: ${e?.message || e}`;
            }
        }

        async function init() {
            try {
                const res = await fetch('/config');
                const config = await res.json();
                if (!config.supabase_url || !config.supabase_key) throw new Error('Supabase Config Missing');
                supabase = window.supabase.createClient(config.supabase_url, config.supabase_key);

                const { data: { session } } = await supabase.auth.getSession();
                if (!session) { window.location.href = '/login'; return; }
                window.__sbAccessToken = (session.access_token || '').trim();
                supabase.auth.onAuthStateChange((_event, nextSession) => {
                    window.__sbAccessToken = (nextSession?.access_token || '').trim();
                });

                // Theme
                const savedTheme = localStorage.getItem('theme_v1');
                if (savedTheme) applyTheme(savedTheme);
                else applyTheme('dark');

                // Admin/UI capabilities
                const me = await loadMe();
                applyAdminUi(me);
                applyIndexingUi(me);
                if (me?.features?.indexing) {
                    loadRagDocuments();
                }

                // Chat sidebar collapse preference (desktop)
                if (localStorage.getItem('chat_sidebar_collapsed_v1') === '1') {
                    toggleChatSidebar(false);
                }

                // Access preferences
                if (localStorage.getItem('auth_allow_signup_v1') == null) {
                    localStorage.setItem('auth_allow_signup_v1', '0');
                }
                // Codex SDK defaults (separate from chat provider)
                if (localStorage.getItem('codex_sdk_base_url_v1') == null) {
                    // Leave blank by default. For device-auth, Codex CLI uses its own auth flow
                    // and default endpoints; setting a base URL without an API key can cause 401s.
                    localStorage.setItem('codex_sdk_base_url_v1', '');
                }
                if (localStorage.getItem('codex_sdk_api_key_v1') == null) {
                    localStorage.setItem('codex_sdk_api_key_v1', '');
                }
                if (localStorage.getItem('codex_sdk_model_v1') == null) {
                    localStorage.setItem('codex_sdk_model_v1', '');
                }
                if (localStorage.getItem('codex_show_jsonl_v1') == null) {
                    localStorage.setItem('codex_show_jsonl_v1', '0');
                }
                if (localStorage.getItem('codex_sandbox_mode_v1') == null) {
                    localStorage.setItem('codex_sandbox_mode_v1', 'danger-full-access');
                }
                if (localStorage.getItem('codex_workdir_v1') == null) {
                    localStorage.setItem('codex_workdir_v1', '');
                }

                // Logged-in user badge (email + username)
                try {
                    const { data: userData } = await supabase.auth.getUser();
                    const user = userData?.user;
                    if (user) {
                        const username =
                            user.user_metadata?.username ||
                            user.user_metadata?.name ||
                            user.user_metadata?.full_name ||
                            (user.email ? user.email.split('@')[0] : '') ||
                            (user.id ? `user-${String(user.id).slice(0, 8)}` : 'User');
                        const email = user.email || '';
                        const badge = document.getElementById('user-badge');
                        const nameEl = document.getElementById('user-name');
                        const emailEl = document.getElementById('user-email');
                        if (badge) badge.classList.remove('hidden');
                        if (nameEl) nameEl.textContent = username;
                        if (emailEl) emailEl.textContent = email;
                    }
                } catch (e) {
                    console.warn('User badge load failed', e);
                }

                document.getElementById('logout-btn').addEventListener('click', async () => {
                    await supabase.auth.signOut();
                    window.location.href = '/login';
                });

                initProviderPresets();
                // Best-effort: hydrate server-persisted MCP registry if local storage is empty.
                maybeHydrateMcpRegistryFromServer();
                // Restore last chat mode (chat/autonomous)
                const savedMode = localStorage.getItem('chat_mode_v1') || 'chat';
                setChatMode(savedMode);

                const ragQuery = document.getElementById('rag-query');
                if (ragQuery) {
                    ragQuery.addEventListener('keydown', (e) => {
                        if (e.key === 'Enter') {
                            e.preventDefault();
                            searchRag();
                        }
                    });
                }

                // Chat bar quick controls
                setChatAgentTarget(getChatAgentTarget());
                syncQuickModelFromSettings();

                // Codex SDK settings UI
                const codexSettings = getCodexSdkSettings();
                const codexBase = document.getElementById('codex-base-url');
                const codexKey = document.getElementById('codex-api-key');
                const codexModel = document.getElementById('codex-model');
                const codexSandbox = document.getElementById('codex-sandbox-mode');
                const codexWorkdir = document.getElementById('codex-workdir');
                if (codexBase) codexBase.value = codexSettings.baseUrl;
                if (codexKey) codexKey.value = codexSettings.apiKey;
                if (codexModel) codexModel.value = codexSettings.model;
                if (codexSandbox) codexSandbox.value = getCodexSandboxMode();
                if (codexWorkdir) codexWorkdir.value = getCodexWorkdir();
                setCodexShowJsonl(getCodexShowJsonl());
                setAgentUseCodexCli(getAgentUseCodexCli());

                // Multi-modal attachments
                const chatFile = document.getElementById('chat-file-input');
                const agentFile = document.getElementById('agent-file-input');
                if (chatFile) {
                    chatFile.addEventListener('change', (e) => {
                        addAttachmentsFromFiles(e.target.files, 'chat');
                        chatFile.value = '';
                    });
                }
                if (agentFile) {
                    agentFile.addEventListener('change', (e) => {
                        addAttachmentsFromFiles(e.target.files, 'agent');
                        agentFile.value = '';
                    });
                }

                const chatInput = document.getElementById('chat-input');
                if (chatInput) {
                    chatInput.addEventListener('paste', (e) => {
                        const items = e.clipboardData?.items || [];
                        const files = [];
                        for (const it of items) {
                            if (it.kind === 'file') {
                                const f = it.getAsFile();
                                if (f && f.type && f.type.startsWith('image/')) files.push(f);
                            }
                        }
                        if (files.length) {
                            addAttachmentsFromFiles(files, 'chat');
                            e.preventDefault();
                        }
                    });
                }

                const agentInput = document.getElementById('agent-chat-input');
                if (agentInput) {
                    agentInput.addEventListener('paste', (e) => {
                        const items = e.clipboardData?.items || [];
                        const files = [];
                        for (const it of items) {
                            if (it.kind === 'file') {
                                const f = it.getAsFile();
                                if (f && f.type && f.type.startsWith('image/')) files.push(f);
                            }
                        }
                        if (files.length) {
                            addAttachmentsFromFiles(files, 'agent');
                            e.preventDefault();
                        }
                    });
                }

                // MCP import
                const mcpImport = document.getElementById('mcp-import-input');
                if (mcpImport) {
                    mcpImport.addEventListener('change', async (e) => {
                        const file = e.target.files?.[0];
                        if (!file) return;
                        try {
                            await importMcpConfigFromFile(file);
                        } catch (err) {
                            alert(`Failed to import mcp.json: ${err?.message || err}`);
                        } finally {
                            mcpImport.value = '';
                        }
                    });
                }

                // Apply defaults if fields are empty
                if (config.default_base_url && !document.getElementById('chat-base-url').value) {
                    document.getElementById('chat-base-url').value = config.default_base_url;
                }
                if (config.default_api_key && !document.getElementById('chat-api-key').value) {
                    document.getElementById('chat-api-key').value = config.default_api_key;
                }
                if (config.default_model && !document.getElementById('chat-model').value) {
                    document.getElementById('chat-model').value = config.default_model;
                }

                // Populate model picker from the configured base URL
                const baseUrlEl = document.getElementById('chat-base-url');
                if (baseUrlEl) {
                    baseUrlEl.addEventListener('change', () => fetchModels().catch(() => { }));
                    baseUrlEl.addEventListener('blur', () => fetchModels().catch(() => { }));
                }
                fetchModels().catch(() => { });

                loadProviders();
                await initNotes();
                await loadChatHistoryList();
                createTerminalTab(); // Init first tab
                applyTerminalLayout();

                // Route helpers
                if (location.pathname === '/settings') openSettings();
                if (location.pathname === '/admin') openAdmin();

            } catch (error) { console.error(error); }
        }

        // --- View Switching ---
        function switchMode(mode) {
            const sections = ['dashboard', 'chat', 'terminal', 'notes'];
            sections.forEach((m) => {
                const el = document.getElementById(`${m}-view`);
                const btn = document.getElementById(`nav-${m}`);
                if (el) el.classList.toggle('hidden', m !== mode);
                if (btn) btn.classList.toggle('bg-gray-700', m === mode);
            });

            if (mode === 'terminal') {
                // Ensure panes are mounted/visible before fitting; hidden views report 0x0 and cause 1-col terminals.
                applyTerminalLayout();
                if (activeTerminalId) setTimeout(() => fitTerm(activeTerminalId), 50);
            }
            if (mode === 'notes') setTimeout(() => { applyNotesLayout(); refreshNotesTree(); }, 0);

            document.getElementById('mobile-menu').classList.add('hidden');
        }

        // --- Terminal Tabs Logic (supports main + agent scopes) ---
        function createTerminalTab({ scope = 'main' } = {}) {
            terminalCount += 1;
            const id = `term-${scope}-${terminalCount}`;
            const containerId = id;

            const tabsEl = scope === 'agent' ? document.getElementById('agent-terminal-tabs') : document.getElementById('terminal-tabs');
            const containersEl = scope === 'agent' ? document.getElementById('agent-terminals-container') : document.getElementById('terminals-container');

            const tabBtn = document.createElement('button');
            tabBtn.id = `tab-btn-${id}`;
            tabBtn.className = "px-3 py-2 text-sm text-gray-200 hover:bg-white/10 border-r border-gray-700/70 flex items-center gap-2";
            tabBtn.innerHTML = `<span>Term ${terminalCount}</span><span class="text-gray-500 hover:text-red-400" title="Close">×</span>`;
            tabBtn.onclick = () => activateTerminalTab(id);
            tabBtn.querySelector('span:last-child').onclick = (e) => closeTerminalTab(id, e);
            tabsEl.appendChild(tabBtn);

            const termDiv = document.createElement('div');
            termDiv.id = containerId;
            termDiv.className = scope === 'agent' ? "absolute inset-0" : "absolute inset-0";
            termDiv.style.display = 'none';
            containersEl.appendChild(termDiv);

            const term = new Terminal({
                convertEol: true,
                fontSize: 14,
                copyOnSelect: true,
                cursorBlink: true,
                fontFamily: '"Ubuntu Mono", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace',
                theme: {
                    background: "#300a24",
                    foreground: "#eeeeec",
                    cursor: "#eeeeec",
                    cursorAccent: "#300a24",
                    selectionBackground: "rgba(238, 238, 236, 0.25)",
                    black: "#2e3436",
                    red: "#cc0000",
                    green: "#4e9a06",
                    yellow: "#c4a000",
                    blue: "#3465a4",
                    magenta: "#75507b",
                    cyan: "#06989a",
                    white: "#d3d7cf",
                    brightBlack: "#555753",
                    brightRed: "#ef2929",
                    brightGreen: "#8ae234",
                    brightYellow: "#fce94f",
                    brightBlue: "#729fcf",
                    brightMagenta: "#ad7fa8",
                    brightCyan: "#34e2e2",
                    brightWhite: "#eeeeec"
                }
            });
            const fitAddon = new FitAddon.FitAddon();
            term.loadAddon(fitAddon);
            term.open(termDiv);

            const token = (window.__sbAccessToken || '').trim();
            const wsUrl = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/terminal` + (token ? `?token=${encodeURIComponent(token)}` : '');
            const ws = new WebSocket(wsUrl);
            // Don't fit immediately here; terminals are often created while their view is hidden.
            ws.onopen = () => { setTimeout(() => fitTerm(id), 0); };
            ws.onmessage = (event) => { term.write(event.data); };
            ws.onclose = () => { term.write('\r\n[disconnected]\r\n'); };

            term.onData((data) => {
                if (ws.readyState === WebSocket.OPEN) ws.send(data);
            });

            const resizeObserver = new ResizeObserver(() => {
                if (!terminals[id]) return;
                if (termDiv.style.display !== 'none') fitTerm(id);
            });
            resizeObserver.observe(termDiv);

            terminals[id] = { term, fitAddon, ws, containerId, scope, resizeObserver };

            // Mobile-friendly copy: double-tap terminal to copy all output.
            termDiv.addEventListener('dblclick', async () => {
                try {
                    term.selectAll();
                    const text = term.getSelection();
                    term.clearSelection();
                    if (text) await navigator.clipboard.writeText(text);
                } catch { }
            });

            if (scope === 'main') {
                applyTerminalLayout();
            } else {
                activateTerminalTab(id);
            }
            return id;
        }

        async function copyActiveTerminalOutput() {
            const id = activeTerminalId;
            const t = terminals[id];
            if (!t || !t.term) return;
            try {
                t.term.selectAll();
                const text = t.term.getSelection();
                t.term.clearSelection();
                if (text) await navigator.clipboard.writeText(text);
            } catch { }
        }

        function activateTerminalTab(id) {
            const t = terminals[id];
            if (!t) return;
            const scope = t.scope || 'main';

            if (scope === 'main') {
                // In split layouts, we can show multiple terminals simultaneously.
                // Keep activeTerminalId for focus and resizing only.
                activeTerminalId = id;
                setTimeout(() => {
                    fitTerm(id);
                    terminals[id].term.focus();
                }, 50);
                return;
            }

            Object.keys(terminals).forEach((tid) => {
                const termInfo = terminals[tid];
                const visible = tid === id;
                const el = document.getElementById(termInfo.containerId);
                if (el) el.style.display = visible ? 'block' : 'none';

                const tab = document.getElementById('tab-btn-' + tid);
                if (tab) {
                    tab.classList.toggle('bg-gray-900', !visible);
                    tab.classList.toggle('bg-gray-800', visible);
                    tab.classList.toggle('border-b-2', visible);
                    tab.classList.toggle('border-blue-500', visible);
                }
            });

            if (scope === 'agent') activeAgentTerminalId = id;
            else activeTerminalId = id;

            setTimeout(() => {
                fitTerm(id);
                terminals[id].term.focus();
            }, 50);
        }

        function closeTerminalTab(id, event) {
            if (event) event.stopPropagation();
            const t = terminals[id];
            if (!t) return;
            const scope = t.scope || 'main';

            const remainingInScope = Object.keys(terminals).filter(tid => (terminals[tid].scope || 'main') === scope && tid !== id);
            if (remainingInScope.length === 0) {
                alert("Cannot close the last terminal in this view.");
                return;
            }

            t.ws.close();
            t.term.dispose();
            try { t.resizeObserver?.disconnect?.(); } catch { }
            document.getElementById(t.containerId).remove();
            document.getElementById('tab-btn-' + id).remove();
            delete terminals[id];

            if (scope === 'agent' && activeAgentTerminalId === id) {
                activateTerminalTab(remainingInScope[remainingInScope.length - 1]);
            }
            if (scope === 'main' && activeTerminalId === id) {
                activeTerminalId = remainingInScope[remainingInScope.length - 1];
                applyTerminalLayout();
            }
        }

        function getTerminalLayout() {
            return localStorage.getItem('terminal_layout_v1') || 'single';
        }

        function setTerminalLayout(layout) {
            const allowed = new Set(['single', 'vsplit', 'hsplit', 'quad']);
            const next = allowed.has(layout) ? layout : 'single';
            localStorage.setItem('terminal_layout_v1', next);
            applyTerminalLayout();
        }

        function applyTerminalLayout() {
            const container = document.getElementById('terminals-container');
            if (!container) return;
            const layout = getTerminalLayout();

            container.classList.remove('single', 'vsplit', 'hsplit', 'quad');
            container.classList.add(layout);

            // Highlight buttons
            ['single', 'vsplit', 'hsplit', 'quad'].forEach((k) => {
                const b = document.getElementById(`layout-${k}`);
                if (!b) return;
                b.classList.toggle('text-white', k === layout);
                b.classList.toggle('bg-gray-700', k === layout);
            });

            const panes = [
                document.getElementById('terminal-pane-1'),
                document.getElementById('terminal-pane-2'),
                document.getElementById('terminal-pane-3'),
                document.getElementById('terminal-pane-4'),
            ].filter(Boolean);

            const maxPanes = layout === 'quad' ? 4 : (layout === 'single' ? 1 : 2);

            panes.forEach((p, idx) => p.classList.toggle('hidden', idx >= maxPanes));

            const ids = Object.keys(terminals)
                .filter((tid) => (terminals[tid].scope || 'main') === 'main')
                .sort((a, b) => {
                    // keep creation order by terminalCount embedded in id suffix
                    const an = Number(a.split('-').pop() || 0);
                    const bn = Number(b.split('-').pop() || 0);
                    return an - bn;
                });

            // Ensure we have an active terminal
            if (!activeTerminalId || !terminals[activeTerminalId] || terminals[activeTerminalId].scope !== 'main') {
                activeTerminalId = ids[ids.length - 1] || null;
            }

            // Choose which terminals to show: active terminal first, then others newest-first
            const ordered = [];
            if (activeTerminalId) ordered.push(activeTerminalId);
            ids.slice().reverse().forEach((tid) => {
                if (ordered.includes(tid)) return;
                ordered.push(tid);
            });
            const visibleIds = ordered.slice(0, maxPanes);

            // Move terminal DOM nodes into panes and show/hide
            visibleIds.forEach((tid, idx) => {
                const termDiv = document.getElementById(terminals[tid].containerId);
                const pane = panes[idx];
                if (!termDiv || !pane) return;
                if (termDiv.parentElement !== pane) pane.appendChild(termDiv);
                termDiv.style.display = 'block';
            });
            ids.forEach((tid) => {
                if (visibleIds.includes(tid)) return;
                const termDiv = document.getElementById(terminals[tid].containerId);
                if (termDiv) termDiv.style.display = 'none';
            });

            // Fit all visible terminals
            setTimeout(() => visibleIds.forEach((tid) => fitTerm(tid)), 0);
        }

        function fitTerm(id, { retries = 10 } = {}) {
            const t = terminals[id];
            if (!t) return;
            const { fitAddon, term, ws, containerId } = t;
            const termDiv = document.getElementById(containerId);
            if (!termDiv) return;

            // If the terminal (or an ancestor view) is hidden, dimensions are 0 and FitAddon produces 1-col terminals.
            const rect = termDiv.getBoundingClientRect();
            const visible = termDiv.getClientRects().length > 0 && rect.width > 40 && rect.height > 40;
            if (!visible) {
                if (retries > 0) setTimeout(() => fitTerm(id, { retries: retries - 1 }), 60);
                return;
            }

            try {
                fitAddon.fit();
                const cols = term.cols;
                const rows = term.rows;
                if (cols >= 2 && rows >= 2 && ws.readyState === WebSocket.OPEN) {
                    ws.send(`\x01resize:${cols}:${rows}`);
                }
            } catch (e) { console.log("Fit error:", e); }
        }

        function initAgentSplitPane() {
            const root = document.getElementById('agent-split-root');
            const paneChat = document.getElementById('agent-pane-chat');
            const paneTerminal = document.getElementById('agent-pane-terminal');
            const divider = document.getElementById('agent-split-divider');
            if (!root || !paneChat || !paneTerminal || !divider) return;

            const key = 'agent_split_ratio_v1';
            const collapseKey = 'agent_terminal_collapsed_v1';
            const clamp = (n, min, max) => Math.max(min, Math.min(max, n));
            const applyRatio = (ratio) => {
                const r = clamp(ratio, 0.2, 0.8);
                paneChat.style.flex = `0 0 ${Math.round(r * 1000) / 10}%`;
                paneTerminal.style.flex = '1 1 auto';
                // Refit visible terminals (agent + main)
                if (activeAgentTerminalId && !document.getElementById('chat-view').classList.contains('hidden')) {
                    setTimeout(() => fitTerm(activeAgentTerminalId), 0);
                }
            };

            const saved = Number(localStorage.getItem(key));
            if (Number.isFinite(saved) && saved > 0) applyRatio(saved);
            else applyRatio(0.48);

            // Restore collapsed state
            const collapsed = localStorage.getItem(collapseKey) === '1';
            if (collapsed) {
                paneTerminal.classList.add('hidden');
                divider.classList.add('hidden');
                paneChat.style.flex = '1 1 auto';
            }

            let dragging = false;
            const onMove = (clientX) => {
                const rect = root.getBoundingClientRect();
                const ratio = (clientX - rect.left) / rect.width;
                applyRatio(ratio);
                localStorage.setItem(key, String(clamp(ratio, 0.2, 0.8)));
            };

            divider.addEventListener('pointerdown', (e) => {
                dragging = true;
                divider.setPointerCapture(e.pointerId);
                document.body.style.cursor = 'col-resize';
                document.body.style.userSelect = 'none';
            });
            divider.addEventListener('pointermove', (e) => {
                if (!dragging) return;
                onMove(e.clientX);
            });
            divider.addEventListener('pointerup', () => {
                dragging = false;
                document.body.style.cursor = '';
                document.body.style.userSelect = '';
            });

            // Keep split sane on window resize
            window.addEventListener('resize', () => {
                const current = Number(localStorage.getItem(key));
                if (Number.isFinite(current) && current > 0) applyRatio(current);
            });
        }

        function toggleAgentTerminalCollapsed() {
            const paneChat = document.getElementById('agent-pane-chat');
            const paneTerminal = document.getElementById('agent-pane-terminal');
            const divider = document.getElementById('agent-split-divider');
            const bar = document.getElementById('agent-terminal-collapsed-bar');
            if (!paneChat || !paneTerminal || !divider) return;
            const key = 'agent_terminal_collapsed_v1';

            const isCollapsed = paneTerminal.classList.contains('hidden');
            if (isCollapsed) {
                paneTerminal.classList.remove('hidden');
                divider.classList.remove('hidden');
                if (bar) bar.classList.add('hidden');
                const ratio = Number(localStorage.getItem('agent_split_ratio_v1')) || 0.48;
                paneChat.style.flex = `0 0 ${Math.round(Math.max(0.2, Math.min(0.8, ratio)) * 1000) / 10}%`;
                paneTerminal.style.flex = '1 1 auto';
                localStorage.setItem(key, '0');
                if (activeAgentTerminalId) setTimeout(() => fitTerm(activeAgentTerminalId), 50);
            } else {
                paneTerminal.classList.add('hidden');
                divider.classList.add('hidden');
                if (bar) bar.classList.remove('hidden');
                paneChat.style.flex = '1 1 auto';
                localStorage.setItem(key, '1');
            }
        }

        function setChatMode(mode) {
            const standard = document.getElementById('chat-standard');
            const auto = document.getElementById('chat-autonomous');
            const btnChat = document.getElementById('chat-mode-chat');
            const btnAuto = document.getElementById('chat-mode-auto');
            if (!standard || !auto) return;
            const m = mode === 'autonomous' ? 'autonomous' : 'chat';

            standard.classList.toggle('hidden', m === 'autonomous');
            auto.classList.toggle('hidden', m !== 'autonomous');
            if (btnChat) btnChat.classList.toggle('bg-white/10', m === 'chat');
            if (btnAuto) btnAuto.classList.toggle('bg-white/10', m === 'autonomous');

            localStorage.setItem('chat_mode_v1', m);
            if (m === 'autonomous') {
                if (!activeAgentTerminalId) activeAgentTerminalId = createTerminalTab({ scope: 'agent' });
                setTimeout(() => {
                    initAgentSplitPane();
                    if (activeAgentTerminalId) fitTerm(activeAgentTerminalId);
                }, 0);
            }
        }

        function openAutonomousMode() {
            switchMode('chat');
            setChatMode('autonomous');
            ensureAgentTerminalVisible();
        }

        window.addEventListener('resize', () => {
            if (activeTerminalId && !document.getElementById('terminal-view').classList.contains('hidden')) fitTerm(activeTerminalId);
            if (activeAgentTerminalId && !document.getElementById('chat-view').classList.contains('hidden') && !document.getElementById('chat-autonomous').classList.contains('hidden')) fitTerm(activeAgentTerminalId);
        });

        // --- Chat Logic ---
        let chatHistory = [];
        let currentSessionId = null;
        let chatAbortController = null;
        let agentAbortController = null;
        let chatImageAttachments = []; // [{ dataUrl, mime }]
        let agentImageAttachments = []; // [{ dataUrl, mime }]
        let chatRecognition = null;
        let agentRecognition = null;
        let chatDictating = false;
        let agentDictating = false;

        function setChatGenerating(isGenerating) {
            const btn = document.getElementById('chat-stop-btn');
            if (!btn) return;
            btn.disabled = !isGenerating;
        }

        function setAgentGenerating(isGenerating) {
            const btn = document.getElementById('agent-stop-btn');
            if (!btn) return;
            btn.disabled = !isGenerating;
        }

        function stopChatGeneration() {
            if (chatAbortController) chatAbortController.abort();
        }

        function stopAgentGeneration() {
            if (agentAbortController) agentAbortController.abort();
        }

        function isSpeechRecognitionSupported() {
            return typeof window !== 'undefined' && (window.SpeechRecognition || window.webkitSpeechRecognition);
        }

        function setMicButtonState(btnId, active) {
            const btn = document.getElementById(btnId);
            if (!btn) return;
            btn.classList.toggle('bg-red-700', !!active);
            btn.classList.toggle('hover:bg-red-600', !!active);
            btn.classList.toggle('bg-gray-700', !active);
            btn.classList.toggle('hover:bg-gray-600', !active);
        }

        function toggleChatDictation() {
            if (!isSpeechRecognitionSupported()) {
                alert('Voice input not supported in this browser.');
                return;
            }
            if (!chatRecognition) {
                const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
                chatRecognition = new SR();
                chatRecognition.continuous = true;
                chatRecognition.interimResults = true;
                chatRecognition.lang = navigator.language || 'en-US';
                chatRecognition.onresult = (event) => {
                    const input = document.getElementById('chat-input');
                    if (!input) return;
                    let finalText = '';
                    let interimText = '';
                    for (let i = event.resultIndex; i < event.results.length; i++) {
                        const res = event.results[i];
                        const text = res[0]?.transcript || '';
                        if (res.isFinal) finalText += text;
                        else interimText += text;
                    }
                    // Append final text; show interim as placeholder
                    if (finalText) {
                        input.value = (input.value ? input.value + ' ' : '') + finalText.trim();
                        input.dispatchEvent(new Event('input'));
                    }
                    input.placeholder = interimText ? interimText.trim() : 'Message...';
                };
                chatRecognition.onerror = () => {
                    chatDictating = false;
                    setMicButtonState('chat-mic-btn', false);
                };
                chatRecognition.onend = () => {
                    chatDictating = false;
                    setMicButtonState('chat-mic-btn', false);
                    const input = document.getElementById('chat-input');
                    if (input) input.placeholder = 'Message...';
                };
            }
            if (chatDictating) {
                chatRecognition.stop();
                chatDictating = false;
                setMicButtonState('chat-mic-btn', false);
            } else {
                chatRecognition.start();
                chatDictating = true;
                setMicButtonState('chat-mic-btn', true);
            }
        }

        function toggleAgentDictation() {
            if (!isSpeechRecognitionSupported()) {
                alert('Voice input not supported in this browser.');
                return;
            }
            if (!agentRecognition) {
                const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
                agentRecognition = new SR();
                agentRecognition.continuous = true;
                agentRecognition.interimResults = true;
                agentRecognition.lang = navigator.language || 'en-US';
                agentRecognition.onresult = (event) => {
                    const input = document.getElementById('agent-chat-input');
                    if (!input) return;
                    let finalText = '';
                    let interimText = '';
                    for (let i = event.resultIndex; i < event.results.length; i++) {
                        const res = event.results[i];
                        const text = res[0]?.transcript || '';
                        if (res.isFinal) finalText += text;
                        else interimText += text;
                    }
                    if (finalText) {
                        input.value = (input.value ? input.value + ' ' : '') + finalText.trim();
                        input.dispatchEvent(new Event('input'));
                    }
                    input.placeholder = interimText ? interimText.trim() : 'Ask agent...';
                };
                agentRecognition.onerror = () => {
                    agentDictating = false;
                    setMicButtonState('agent-mic-btn', false);
                };
                agentRecognition.onend = () => {
                    agentDictating = false;
                    setMicButtonState('agent-mic-btn', false);
                    const input = document.getElementById('agent-chat-input');
                    if (input) input.placeholder = 'Ask agent...';
                };
            }
            if (agentDictating) {
                agentRecognition.stop();
                agentDictating = false;
                setMicButtonState('agent-mic-btn', false);
            } else {
                agentRecognition.start();
                agentDictating = true;
                setMicButtonState('agent-mic-btn', true);
            }
        }

        function guessMimeFromDataUrl(dataUrl) {
            const m = /^data:([^;]+);base64,/.exec(dataUrl || '');
            return m ? m[1] : 'image/png';
        }

        function renderAttachmentStrip(containerId, attachments, onRemove) {
            const el = document.getElementById(containerId);
            if (!el) return;
            if (!attachments.length) {
                el.classList.add('hidden');
                el.innerHTML = '';
                return;
            }
            el.classList.remove('hidden');
            el.className = ('attachment-strip ' + (el.className || '')).replace(/\s+/g, ' ').trim();
            el.innerHTML = '';
            attachments.forEach((a, idx) => {
                const wrap = document.createElement('div');
                wrap.className = 'attachment-thumb';
                wrap.innerHTML = `<img alt="attachment" src="${a.dataUrl}">`;
                const btn = document.createElement('button');
                btn.type = 'button';
                btn.title = 'Remove';
                btn.textContent = '×';
                btn.onclick = () => onRemove(idx);
                wrap.appendChild(btn);
                el.appendChild(wrap);
            });
        }

        function renderChatAttachments() {
            renderAttachmentStrip('chat-attachments', chatImageAttachments, (i) => {
                chatImageAttachments.splice(i, 1);
                renderChatAttachments();
            });
        }

        function renderAgentAttachments() {
            renderAttachmentStrip('agent-attachments', agentImageAttachments, (i) => {
                agentImageAttachments.splice(i, 1);
                renderAgentAttachments();
            });
        }

        function addAttachmentsFromFiles(files, target) {
            const list = Array.from(files || []).filter(f => f && f.type && f.type.startsWith('image/'));
            if (!list.length) return;
            list.forEach((file) => {
                const reader = new FileReader();
                reader.onload = () => {
                    const dataUrl = String(reader.result || '');
                    const entry = { dataUrl, mime: file.type || guessMimeFromDataUrl(dataUrl) };
                    if (target === 'chat') {
                        chatImageAttachments.push(entry);
                        renderChatAttachments();
                    } else {
                        agentImageAttachments.push(entry);
                        renderAgentAttachments();
                    }
                };
                reader.readAsDataURL(file);
            });
        }

        async function captureScreenshotDataUrl() {
            if (!navigator.mediaDevices?.getDisplayMedia) {
                throw new Error('Screen capture not supported in this browser.');
            }
            const stream = await navigator.mediaDevices.getDisplayMedia({ video: true, audio: false });
            try {
                const track = stream.getVideoTracks()[0];
                const settings = track.getSettings?.() || {};
                const video = document.createElement('video');
                video.srcObject = stream;
                video.muted = true;
                await video.play();

                const width = settings.width || video.videoWidth || 1280;
                const height = settings.height || video.videoHeight || 720;
                const canvas = document.createElement('canvas');
                canvas.width = width;
                canvas.height = height;
                const ctx = canvas.getContext('2d');
                ctx.drawImage(video, 0, 0, width, height);
                return canvas.toDataURL('image/png');
            } finally {
                stream.getTracks().forEach(t => t.stop());
            }
        }

        async function captureScreenshotToChat() {
            try {
                const dataUrl = await captureScreenshotDataUrl();
                chatImageAttachments.push({ dataUrl, mime: 'image/png' });
                renderChatAttachments();
            } catch (e) {
                alert(e?.message || e);
            }
        }

        async function captureScreenshotToAgent() {
            try {
                const dataUrl = await captureScreenshotDataUrl();
                agentImageAttachments.push({ dataUrl, mime: 'image/png' });
                renderAgentAttachments();
            } catch (e) {
                alert(e?.message || e);
            }
        }

        async function startNewChat() {
            currentSessionId = null;
            chatHistory = [];
            localStorage.removeItem('codex_thread_id_v1');
            document.getElementById('current-chat-title').textContent = "New Chat";
            document.getElementById('chat-history').innerHTML = '';
            document.getElementById('chat-input').value = '';
            if (window.innerWidth < 768) {
                document.querySelector('#chat-view .w-64').classList.add('hidden');
            }
        }

        async function loadChatHistoryList() {
            const { data: { user } } = await supabase.auth.getUser();
            if (!user) return;
            const { data, error } = await supabase.from('chat_sessions').select('*').eq('user_id', user.id).order('created_at', { ascending: false });
            if (error) return console.error(error);

            const list = document.getElementById('history-list');
            list.innerHTML = '';
            if (data && data.length > 0) {
                data.forEach(session => {
                    const row = document.createElement('div');
                    row.className = "w-full flex items-center gap-2 p-2 hover:bg-gray-700 rounded text-gray-300 text-sm group mb-1";

                    const titleBtn = document.createElement('button');
                    titleBtn.type = 'button';
                    titleBtn.className = "flex-grow text-left truncate";
                    titleBtn.textContent = session.title || 'Untitled';
                    titleBtn.onclick = () => loadChatSession(session.id, session.title || 'Untitled');

                    const delBtn = document.createElement('button');
                    delBtn.type = 'button';
                    delBtn.className = "shrink-0 opacity-0 group-hover:opacity-100 transition text-gray-400 hover:text-red-300";
                    delBtn.title = "Delete chat";
                    delBtn.onclick = (e) => { e.stopPropagation(); deleteChatSession(session.id); };
                    delBtn.innerHTML = `
                        <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor" class="w-4 h-4">
                            <path fill-rule="evenodd" d="M9 3.75A2.25 2.25 0 0 1 11.25 1.5h1.5A2.25 2.25 0 0 1 15 3.75V4.5h4.5a.75.75 0 0 1 0 1.5h-.75l-1.02 14.28A2.25 2.25 0 0 1 15.486 22.5H8.514a2.25 2.25 0 0 1-2.244-2.22L5.25 6h-.75a.75.75 0 0 1 0-1.5H9V3.75Zm1.5.75V3.75a.75.75 0 0 1 .75-.75h1.5a.75.75 0 0 1 .75.75V4.5h-3ZM8.04 6l.75 13.5a.75.75 0 0 0 .75.75h4.92a.75.75 0 0 0 .75-.75L15.96 6H8.04ZM10.5 9a.75.75 0 0 1 .75.75v7.5a.75.75 0 0 1-1.5 0v-7.5A.75.75 0 0 1 10.5 9Zm3 0a.75.75 0 0 1 .75.75v7.5a.75.75 0 0 1-1.5 0v-7.5A.75.75 0 0 1 13.5 9Z" clip-rule="evenodd" />
                        </svg>`;

                    row.appendChild(titleBtn);
                    row.appendChild(delBtn);
                    list.appendChild(row);
                });
            }
        }

        async function deleteChatSession(sessionId) {
            if (!sessionId) return;
            if (!confirm("Delete this chat? This cannot be undone.")) return;

            try {
                // Delete messages first (if FK constraints exist)
                const { error: msgErr } = await supabase.from('chat_messages').delete().eq('session_id', sessionId);
                if (msgErr) throw msgErr;

                const { error: sessErr } = await supabase.from('chat_sessions').delete().eq('id', sessionId);
                if (sessErr) throw sessErr;

                if (currentSessionId === sessionId) {
                    await startNewChat();
                }
                await loadChatHistoryList();
            } catch (e) {
                console.error(e);
                alert(`Failed to delete chat: ${e?.message || e}`);
            }
        }

        async function loadChatSession(sessionId, title) {
            currentSessionId = sessionId;
            document.getElementById('current-chat-title').textContent = title;
            document.getElementById('chat-history').innerHTML = '<div class="text-center text-gray-500 mt-4">Loading...</div>';
            if (window.innerWidth < 768) document.querySelector('#chat-view .w-64').classList.add('hidden');

            const { data } = await supabase.from('chat_messages').select('*').eq('session_id', sessionId).order('created_at', { ascending: true });
            document.getElementById('chat-history').innerHTML = '';
            chatHistory = [];
            if (data) {
                data.forEach(msg => {
                    addMessageToUI(msg.role === 'user' ? 'user' : 'assistant', msg.content);
                    chatHistory.push({ role: msg.role, content: msg.content });
                });
                scrollToBottom();
            }
        }

        async function sendMessage() {
            const input = document.getElementById('chat-input');
            const message = input.value.trim();
            if (!message && chatImageAttachments.length === 0) return;
            if (chatAbortController) chatAbortController.abort();

            // Build multimodal user message (text + optional images)
            const parts = [];
            if (message) parts.push({ type: 'text', text: message });
            chatImageAttachments.forEach((a) => {
                parts.push({ type: 'image_url', image_url: { url: a.dataUrl } });
            });
            addMessageToUI('user', message || (chatImageAttachments.length ? '[image]' : ''));
            if (chatImageAttachments.length) {
                const imgWrap = document.createElement('div');
                imgWrap.className = 'attachment-strip mt-2';
                chatImageAttachments.forEach((a) => {
                    const img = document.createElement('img');
                    img.src = a.dataUrl;
                    img.alt = 'attachment';
                    img.className = 'attachment-thumb';
                    img.style.width = '120px';
                    img.style.height = '86px';
                    imgWrap.appendChild(img);
                });
                document.getElementById('chat-history').lastChild.appendChild(imgWrap);
            }
            chatHistory.push({ role: 'user', content: parts.length === 1 && parts[0].type === 'text' ? parts[0].text : parts });
            input.value = '';
            chatImageAttachments = [];
            renderChatAttachments();
            scrollToBottom();

            // Save to DB
            if (!currentSessionId) {
                const { data: { user } } = await supabase.auth.getUser();
                const { data } = await supabase.from('chat_sessions').insert({ user_id: user.id, title: message.substring(0, 30) }).select().single();
                if (data) {
                    currentSessionId = data.id;
                    loadChatHistoryList();
                }
            }
            if (currentSessionId) await supabase.from('chat_messages').insert({ session_id: currentSessionId, role: 'user', content: message || (parts.length ? '[attachment]' : '') });

            // AI Request
            const apiKey = document.getElementById('chat-api-key').value;
            const baseUrl = document.getElementById('chat-base-url').value;
            const model = document.getElementById('chat-model').value;
            const aiMsgEl = addMessageToUI('assistant', '...');
            let aiContent = '';

            try {
                chatAbortController = new AbortController();
                setChatGenerating(true);
                const res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ messages: chatHistory, apiKey, baseUrl, model }),
                    signal: chatAbortController.signal
                });

                const reader = res.body.getReader();
                const decoder = new TextDecoder();
                aiMsgEl.innerHTML = '';

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    aiContent += decoder.decode(value);
                aiMsgEl.innerText = aiContent; // Simple stream render
                scrollToBottom();
                }
                // Final Markdown
                renderMarkdownInto(aiMsgEl, aiContent);

                chatHistory.push({ role: 'assistant', content: aiContent });
                if (currentSessionId) await supabase.from('chat_messages').insert({ session_id: currentSessionId, role: 'assistant', content: aiContent });

            } catch (error) {
                if (error?.name === 'AbortError') {
                    aiMsgEl.textContent = aiContent ? aiContent : "[stopped]";
                } else {
                    aiMsgEl.textContent = "Error: " + error.message;
                }
            } finally {
                setChatGenerating(false);
                chatAbortController = null;
            }
        }

        function addMessageToUI(role, content) {
            const div = document.createElement('div');
            div.className = `chat-message ${role === 'user' ? 'user-message self-end' : 'ai-message self-start'} max-w-[85%] p-3 rounded-xl my-2 prose prose-invert break-words text-sm md:text-base shadow-sm`;
            renderMarkdownInto(div, content);
            const container = document.getElementById('chat-history');
            const empty = document.getElementById('chat-empty-state');
            if (empty) empty.remove();
            container.appendChild(div);
            return div;
        }

        function scrollToBottom() {
            const container = document.getElementById('chat-history');
            container.scrollTop = container.scrollHeight;
        }

        function handleEnter(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendChatBarMessage();
            }
        }

        function getChatAgentTarget() {
            return localStorage.getItem('chat_agent_target_v1') || 'chat';
        }

        function setChatAgentTarget(target) {
            const t = target === 'codex' ? 'codex' : 'chat';
            localStorage.setItem('chat_agent_target_v1', t);
            const sel = document.getElementById('chat-agent-target');
            if (sel) sel.value = t;
        }

        function setQuickModel(model) {
            const m = (model || '').trim();
            if (!m) return;
            const main = document.getElementById('chat-model');
            if (main) main.value = m;
            const quick = document.getElementById('chat-model-quick');
            if (quick) quick.value = m;
        }

        function syncQuickModelFromSettings() {
            const main = document.getElementById('chat-model');
            const quick = document.getElementById('chat-model-quick');
            if (main && quick) quick.value = main.value || '';
        }

        function getCodexThreadId() {
            return localStorage.getItem('codex_thread_id_v1') || '';
        }

        function setCodexThreadId(id) {
            if (id) localStorage.setItem('codex_thread_id_v1', id);
        }

        function getAgentCodexThreadId() {
            return localStorage.getItem('codex_agent_thread_id_v1') || '';
        }

        function setAgentCodexThreadId(id) {
            if (id) localStorage.setItem('codex_agent_thread_id_v1', id);
        }

        function resetCodexThread() {
            localStorage.removeItem('codex_thread_id_v1');
            localStorage.removeItem('codex_agent_thread_id_v1');
            const out = document.getElementById('codex-mcp-list');
            if (out) out.textContent = 'Codex threads cleared.';
        }

        async function getCodexLoginStatus() {
            try {
                const res = await authFetch('/api/codex/login/status');
                if (!res.ok) return { loggedIn: false, statusText: `HTTP ${res.status}` };
                return await res.json();
            } catch (e) {
                return { loggedIn: false, statusText: String(e?.message || e) };
            }
        }

        async function ensureCodexAuthenticated() {
            const status = await getCodexLoginStatus();
            if (status.loggedIn) return true;

            const baseTip = [
                "Codex needs authentication.",
                "",
                "Run device login in the terminal:",
                "```bash",
                "codex login --device-auth",
                "```",
                "",
                `Status: ${status.statusText || 'Not logged in'}`,
            ].join("\n");

            addMessageToUI('assistant', baseTip);

            // Auto-open terminal and run once per browser session for convenience.
            if (sessionStorage.getItem('codex_device_auth_autoran_v2') !== '1') {
                sessionStorage.setItem('codex_device_auth_autoran_v2', '1');
                runInTerminal('codex login --device-auth\n', { preferScope: 'main', autoShow: true });
            }

            return false;
        }

        async function sendCodexSdkMessage(message) {
            const codex = getCodexSdkSettings();
            const apiKey = codex.apiKey || '';
            // Only pass baseUrl when using API key auth; device-auth should rely on Codex defaults.
            const baseUrl = apiKey ? (codex.baseUrl || '') : '';
            const model = (codex.model || '').trim();
            const showJsonl = getCodexShowJsonl();
            const sandboxMode = getCodexSandboxMode();

            addMessageToUI('user', message || '');
            scrollToBottom();

            const aiMsgEl = addMessageToUI('assistant', '...');
            aiMsgEl.innerHTML = '';

            try {
                const res = await authFetch('/api/codex/cli/stream', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        message,
                        threadId: getCodexThreadId() || null,
                        model: model || null,
                        sandboxMode,
                        approvalPolicy: 'never',
                        modelReasoningEffort: 'minimal',
                        workingDirectory: getCodexWorkdir() || null,
                        apiKey: apiKey || null,
                        baseUrl: baseUrl || null
                    })
                });
                if (!res.ok) {
                    const txt = await res.text();
                    if (res.status === 401) {
                        const status = await getCodexLoginStatus();
                        const tip = [
                            "Codex needs authentication.",
                            "",
                            "Run device login in the terminal (use the Run button):",
                            "```bash",
                            "codex login --device-auth",
                            "```",
                            "",
                            "Or paste an API key in Settings → Codex SDK.",
                            status?.statusText ? `\nStatus: ${status.statusText}` : ""
                        ].join("\n");
                        renderMarkdownInto(aiMsgEl, tip);

                        // Avoid looping: only auto-run once per browser session.
                        if (sessionStorage.getItem('codex_device_auth_autoran_v1') !== '1') {
                            sessionStorage.setItem('codex_device_auth_autoran_v1', '1');
                            runInTerminal('codex login --device-auth\n', { preferScope: 'main', autoShow: true });
                        }
                        return;
                    }
                    throw new Error(txt || `HTTP ${res.status}`);
                }

                const reader = res.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';
                let finalText = '';
                let threadId = null;
                const progress = [];

                const pushProgress = (line) => {
                    if (!line) return;
                    progress.push(line);
                    if (progress.length > 400) progress.splice(0, progress.length - 400);
                };

                const summarizeEvent = (evt) => {
                    const t = evt?.type || 'event';
                    if (t === 'thread.started') return `thread.started: ${evt.thread_id || ''}`.trim();
                    if (t === 'turn.completed') return `turn.completed: in=${evt.usage?.input_tokens || 0} out=${evt.usage?.output_tokens || 0}`;
                    if (t === 'turn.failed') return `turn.failed: ${evt.error?.message || evt.message || ''}`.trim();
                    if (t === 'stderr') return `stderr: ${evt.message || ''}`.trim();
                    if (t === 'log') return `log: ${evt.message || ''}`.trim();
                    if (t === 'done') return `done: rc=${evt.returnCode ?? ''}`.trim();
                    const itemType = evt?.item?.type;
                    if (itemType && (t === 'item.started' || t === 'item.updated' || t === 'item.completed')) {
                        const name = evt?.item?.name || evt?.item?.tool_name || '';
                        const extra = name ? ` (${name})` : '';
                        return `${t}: ${itemType}${extra}`;
                    }
                    return t;
                };

                const renderProgress = () => {
                    const content = [
                        progress.length ? 'Progress:' : '',
                        progress.length ? '```text\n' + progress.slice(-30).join('\n') + '\n```' : '',
                        finalText ? '\n\n' + finalText : ''
                    ].filter(Boolean).join('\n');
                    renderMarkdownInto(aiMsgEl, content || '...');
                    scrollToBottom();
                };

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop() || '';
                    for (const line of lines) {
                        if (!line.trim()) continue;
                        let evt;
                        try { evt = JSON.parse(line); } catch { continue; }
                        pushProgress(summarizeEvent(evt));
                        if (showJsonl) pushProgress(JSON.stringify(evt));
                        if (evt.type === 'thread.started' && evt.thread_id) {
                            threadId = evt.thread_id;
                            setCodexThreadId(threadId);
                        } else if (evt.type === 'item.completed' && evt.item?.type === 'agent_message') {
                            finalText = evt.item.text || finalText;
                        } else if (evt.type === 'done') {
                            if (evt.threadId) setCodexThreadId(evt.threadId);
                            if (evt.finalResponse) finalText = evt.finalResponse;
                        }
                        renderProgress();
                    }
                }

                // Final render (in case only done event carried finalResponse)
                renderMarkdownInto(aiMsgEl, finalText || (progress.length ? progress.slice(-30).join('\n') : ''));
            } catch (e) {
                aiMsgEl.textContent = `Error: ${e?.message || e}`;
            }
        }

        async function sendChatBarMessage() {
            const input = document.getElementById('chat-input');
            const raw = (input?.value || '').trim();
            if (raw === '/mcp') {
                if (input) input.value = '';
                addMessageToUI('user', '/mcp');
                const ai = addMessageToUI('assistant', 'Loading MCP tools...');
                try {
                    const res = await authFetch('/api/mcp/tools');
                    const data = await res.json();
                    const tools = Array.isArray(data?.tools) ? data.tools : [];
                    if (!tools.length) {
                        renderMarkdownInto(ai, 'No MCP tools available.');
                        return;
                    }
                    const lines = [
                        `Available MCP tools (${tools.length}):`,
                        '',
                        ...tools.map((t) => `- \`${t?.name || 'tool'}\` — ${t?.description || ''}`),
                        '',
                        'Details:',
                        '```json',
                        JSON.stringify(tools, null, 2),
                        '```',
                    ].join('\n');
                    renderMarkdownInto(ai, lines);
                } catch (e) {
                    ai.textContent = `Failed to load MCP tools: ${e?.message || e}`;
                }
                return;
            }
            const explicitCodex = raw.toLowerCase().startsWith('@codex');
            const target = explicitCodex ? 'codex' : getChatAgentTarget();

            if (target === 'codex') {
                const message = raw.replace(/^@codex\b\s*/i, '');
                if (input) input.value = '';
                const ok = await ensureCodexAuthenticated();
                if (!ok) return;
                return sendCodexSdkMessage(message);
            }

            return sendMessage();
        }

        // --- Autonomous Mode (Agent) ---
        let agentChatHistory = [];
        async function sendAgentMessage() {
            const input = document.getElementById('agent-chat-input');
            const message = (input.value || '').trim();
            if (!message && agentImageAttachments.length === 0) return;
            if (agentAbortController) agentAbortController.abort();

            const parts = [];
            if (message) parts.push({ type: 'text', text: message });
            agentImageAttachments.forEach((a) => {
                parts.push({ type: 'image_url', image_url: { url: a.dataUrl } });
            });

            addAgentMessageToUI('user', message || (agentImageAttachments.length ? '[image]' : ''));
            if (agentImageAttachments.length) {
                const imgWrap = document.createElement('div');
                imgWrap.className = 'attachment-strip mt-2';
                agentImageAttachments.forEach((a) => {
                    const img = document.createElement('img');
                    img.src = a.dataUrl;
                    img.alt = 'attachment';
                    img.className = 'attachment-thumb';
                    img.style.width = '120px';
                    img.style.height = '86px';
                    imgWrap.appendChild(img);
                });
                document.getElementById('agent-chat-history').lastChild.appendChild(imgWrap);
            }
            agentChatHistory.push({ role: 'user', content: parts.length === 1 && parts[0].type === 'text' ? parts[0].text : parts });
            input.value = '';
            agentImageAttachments = [];
            renderAgentAttachments();
            scrollAgentToBottom();

            const model = document.getElementById('chat-model').value;

            const aiMsgEl = addAgentMessageToUI('assistant', '...');
            let aiContent = '';
            try {
                agentAbortController = new AbortController();
                setAgentGenerating(true);
                if (getAgentUseCodexCli()) {
                    const ok = await ensureCodexAuthenticated();
                    if (!ok) throw new Error('Codex not authenticated');
                    const codex = getCodexSdkSettings();
                    const codexModel = (codex.model || '').trim();
                    const existingThreadId = getAgentCodexThreadId() || null;

                    const res = await authFetch('/api/codex/cli/stream', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({
                            message,
                            threadId: existingThreadId,
                            model: codexModel || null,
                            sandboxMode: 'workspace-write',
                            approvalPolicy: 'never',
                            modelReasoningEffort: 'minimal',
                            workingDirectory: getCodexWorkdir() || null
                        }),
                        signal: agentAbortController.signal
                    });

                    if (!res.ok) {
                        const txt = await res.text();
                        throw new Error(txt || `HTTP ${res.status}`);
                    }

                    const reader = res.body.getReader();
                    const decoder = new TextDecoder();
                    let buffer = '';
                    let finalText = '';
                    let threadId = existingThreadId;
                    const progress = [];

                    const pushProgress = (line) => {
                        if (!line) return;
                        progress.push(line);
                        if (progress.length > 200) progress.splice(0, progress.length - 200);
                    };

                    const summarizeEvent = (evt) => {
                        const t = evt?.type || 'event';
                        if (t === 'thread.started') return `thread.started: ${evt.thread_id || ''}`.trim();
                        if (t === 'turn.completed') return `turn.completed: in=${evt.usage?.input_tokens || 0} out=${evt.usage?.output_tokens || 0}`;
                        if (t === 'turn.failed') return `turn.failed: ${evt.error?.message || evt.message || ''}`.trim();
                        if (t === 'stderr') return `stderr: ${evt.message || ''}`.trim();
                        if (t === 'done') return `done: rc=${evt.returnCode ?? ''}`.trim();
                        const itemType = evt?.item?.type;
                        if (itemType && (t === 'item.started' || t === 'item.updated' || t === 'item.completed')) {
                            const name = evt?.item?.name || evt?.item?.tool_name || '';
                            const extra = name ? ` (${name})` : '';
                            return `${t}: ${itemType}${extra}`;
                        }
                        return t;
                    };

                    const renderProgress = () => {
                        const content = [
                            progress.length ? 'Progress:' : '',
                            progress.length ? '```text\n' + progress.slice(-18).join('\n') + '\n```' : '',
                            finalText ? '\n\n' + finalText : ''
                        ].filter(Boolean).join('\n');
                        renderMarkdownInto(aiMsgEl, content || '...');
                        scrollAgentToBottom();
                    };

                    while (true) {
                        const { done, value } = await reader.read();
                        if (done) break;
                        buffer += decoder.decode(value, { stream: true });
                        const lines = buffer.split('\n');
                        buffer = lines.pop() || '';
                        for (const line of lines) {
                            if (!line.trim()) continue;
                            let evt;
                            try { evt = JSON.parse(line); } catch { continue; }
                            pushProgress(summarizeEvent(evt));
                            if (evt.type === 'thread.started' && evt.thread_id) {
                                threadId = evt.thread_id;
                                setAgentCodexThreadId(threadId);
                            }
                            if (evt.type === 'item.updated' && evt.item?.type === 'agent_message' && evt.item?.text) {
                                finalText = evt.item.text || finalText;
                            } else if (evt.type === 'item.completed' && evt.item?.type === 'agent_message') {
                                finalText = evt.item.text || finalText;
                            } else if (evt.type === 'done') {
                                if (evt.threadId) {
                                    threadId = evt.threadId;
                                    setAgentCodexThreadId(threadId);
                                }
                                if (evt.finalResponse) finalText = evt.finalResponse;
                            }
                            renderProgress();
                        }
                    }

                    aiContent = finalText;
                    renderMarkdownInto(aiMsgEl, aiContent || (progress.length ? progress.slice(-18).join('\n') : ''));
                    agentChatHistory.push({ role: 'assistant', content: aiContent || '' });
                } else {
                    const apiKey = document.getElementById('chat-api-key').value;
                    const baseUrl = document.getElementById('chat-base-url').value;
                    const res = await fetch('/api/chat', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ messages: agentChatHistory, apiKey, baseUrl, model }),
                        signal: agentAbortController.signal
                    });
                    const reader = res.body.getReader();
                    const decoder = new TextDecoder();
                    aiMsgEl.innerHTML = '';

                    while (true) {
                        const { done, value } = await reader.read();
                        if (done) break;
                        aiContent += decoder.decode(value);
                        aiMsgEl.innerText = aiContent;
                        scrollAgentToBottom();
                    }

                    renderMarkdownInto(aiMsgEl, aiContent);
                    agentChatHistory.push({ role: 'assistant', content: aiContent });
                }
            } catch (error) {
                if (error?.name === 'AbortError') {
                    aiMsgEl.textContent = aiContent ? aiContent : "[stopped]";
                } else {
                    aiMsgEl.textContent = "Error: " + error.message;
                }
            } finally {
                setAgentGenerating(false);
                agentAbortController = null;
            }
        }

        function handleAgentEnter(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendAgentMessage();
            }
        }

        function addAgentMessageToUI(role, content) {
            const div = document.createElement('div');
            div.className = `chat-message ${role === 'user' ? 'user-message self-end' : 'ai-message self-start'} max-w-[85%] p-3 rounded-xl my-2 prose prose-invert break-words text-sm md:text-base shadow-sm`;
            renderMarkdownInto(div, content);
            const container = document.getElementById('agent-chat-history');
            const empty = document.getElementById('agent-empty-state');
            if (empty) empty.remove();
            container.appendChild(div);
            return div;
        }

        function scrollAgentToBottom() {
            const container = document.getElementById('agent-chat-history');
            container.scrollTop = container.scrollHeight;
        }

        // --- MCP Admin ---
        const MCP_STORAGE_KEY = 'mcp_servers_v1';

        async function maybeHydrateMcpRegistryFromServer() {
            try {
                const raw = localStorage.getItem(MCP_STORAGE_KEY);
                if (raw && raw.trim() && raw.trim() !== '[]') return;
                await loadMcpRegistryFromServer({ quiet: true });
            } catch { }
        }

        async function loadMcpRegistryFromServer({ quiet = false } = {}) {
            const statusEl = document.getElementById('codex-mcp-list');
            try {
                if (statusEl && !quiet) statusEl.textContent = 'Loading MCP registry from server...';
                const res = await authFetch('/api/user/mcp-registry');
                if (!res.ok) throw new Error(await res.text());
                const data = await res.json();
                const servers = Array.isArray(data?.servers) ? data.servers : [];
                localStorage.setItem(MCP_STORAGE_KEY, JSON.stringify(servers));
                renderMcpServersInto('settings-mcp-server-list', { compact: true });
                if (statusEl && !quiet) statusEl.textContent = `Loaded MCP registry (${servers.length}) from server.`;
            } catch (e) {
                if (!quiet) alert(`Failed to load MCP registry: ${e?.message || e}`);
                if (statusEl && !quiet) statusEl.textContent = 'Failed to load MCP registry from server.';
            }
        }

        async function saveMcpRegistryToServer() {
            const statusEl = document.getElementById('codex-mcp-list');
            try {
                if (statusEl) statusEl.textContent = 'Saving MCP registry to server...';
                const servers = loadMcpServers();
                const res = await authFetch('/api/user/mcp-registry', {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ version: 1, servers }),
                });
                if (!res.ok) throw new Error(await res.text());
                const data = await res.json();
                if (statusEl) statusEl.textContent = `Saved MCP registry (${data?.count ?? servers.length}) to server.`;
            } catch (e) {
                alert(`Failed to save MCP registry: ${e?.message || e}`);
                if (statusEl) statusEl.textContent = 'Failed to save MCP registry to server.';
            }
        }

        function loadMcpServers() {
            try {
                return JSON.parse(localStorage.getItem(MCP_STORAGE_KEY) || '[]');
            } catch {
                return [];
            }
        }

        function saveMcpServers(servers) {
            localStorage.setItem(MCP_STORAGE_KEY, JSON.stringify(servers || []));
            renderMcpServers();
        }

        function addMcpServerPrompt() {
            const name = prompt('Server name (e.g., "local-mcp")');
            if (!name) return;
            const url = prompt('Server URL (e.g., "http://localhost:9000")');
            if (!url) return;
            const servers = loadMcpServers();
            servers.push({
                id: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
                name,
                url,
                apiKey: '',
                token: '',
                headersJson: '{}',
                toolsJson: '[]'
            });
            saveMcpServers(servers);
        }

        function addMcpServerByUrl() {
            const urlEl = document.getElementById('mcp-direct-url');
            const url = (urlEl?.value || '').trim();
            if (!url) return;
            const name = url.replace(/^https?:\/\//, '').replace(/\/+$/, '');
            const servers = loadMcpServers();
            servers.push({
                id: crypto.randomUUID ? crypto.randomUUID() : String(Date.now()),
                name,
                url,
                apiKey: '',
                token: '',
                headersJson: '{}',
                toolsJson: '[]'
            });
            saveMcpServers(servers);
            if (urlEl) urlEl.value = '';
        }

        function exportMcpConfig() {
            const servers = loadMcpServers().map((s) => {
                let headers = {};
                let tools = [];
                try { headers = s.headersJson ? JSON.parse(s.headersJson) : {}; } catch { headers = {}; }
                try { tools = s.toolsJson ? JSON.parse(s.toolsJson) : []; } catch { tools = []; }
                return {
                    id: s.id,
                    name: s.name,
                    url: s.url,
                    auth: { apiKey: s.apiKey || '', token: s.token || '' },
                    headers,
                    tools
                };
            });
            const payload = { version: 1, servers };
            const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
            const a = document.createElement('a');
            a.href = URL.createObjectURL(blob);
            a.download = 'mcp.json';
            a.click();
            setTimeout(() => URL.revokeObjectURL(a.href), 500);
        }

        async function importMcpConfigFromFile(file) {
            if (!file) throw new Error('No file provided');
            if (file.size > 1_000_000) throw new Error('mcp.json too large (max 1MB)');
            const text = await file.text();
            const parsed = JSON.parse(text || '{}');
            if (parsed?.version != null && Number(parsed.version) !== 1) {
                throw new Error('Unsupported mcp.json version');
            }
            const servers = Array.isArray(parsed?.servers) ? parsed.servers : [];
            const normalized = servers
                .filter((s) => s && typeof s === 'object')
                .map((s) => {
                    const rawUrl = String(s.url || '').trim();
                    const urlOk = /^https?:\/\//i.test(rawUrl);
                    const id = String(s.id || '').trim() || (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()));
                    const name = String(s.name || s.id || 'mcp-server').trim().slice(0, 80);

                    const auth = s.auth && typeof s.auth === 'object' ? s.auth : {};
                    const apiKey = String(auth.apiKey || '').trim();
                    const token = String(auth.token || '').trim();

                    const headers = s.headers && typeof s.headers === 'object' && !Array.isArray(s.headers) ? s.headers : {};
                    const toolsRaw = Array.isArray(s.tools) ? s.tools : [];
                    const tools = toolsRaw.map((t) => String(t || '').trim()).filter(Boolean).slice(0, 200);

                    return {
                        id,
                        name,
                        url: urlOk ? rawUrl : '',
                        apiKey,
                        token,
                        headersJson: JSON.stringify(headers, null, 2),
                        toolsJson: JSON.stringify(tools, null, 2),
                    };
                })
                .filter((s) => s.url);
            if (!normalized.length) throw new Error('No valid servers found in mcp.json');
            saveMcpServers(normalized);
        }

        function deleteMcpServer(id) {
            if (!confirm('Delete this MCP server?')) return;
            const servers = loadMcpServers().filter(s => s.id !== id);
            saveMcpServers(servers);
        }

        function updateMcpServer(id, patch) {
            const servers = loadMcpServers().map(s => (s.id === id ? { ...s, ...patch } : s));
            saveMcpServers(servers);
        }

        async function testMcpServer(id, statusElementId = null) {
            const statusEl = document.getElementById(statusElementId || `mcp-status-${id}`);
            const server = loadMcpServers().find(s => s.id === id);
            if (!server) return;
            if (statusEl) statusEl.textContent = 'Testing...';

            let extraHeaders = {};
            try {
                extraHeaders = server.headersJson ? JSON.parse(server.headersJson) : {};
            } catch (e) {
                if (statusEl) statusEl.textContent = 'Invalid headers JSON';
                return;
            }

            const headers = {
                ...extraHeaders
            };
            if (server.apiKey) headers['x-api-key'] = server.apiKey;
            if (server.token) headers['Authorization'] = `Bearer ${server.token}`;

            try {
                const res = await fetch(server.url, { method: 'GET', headers });
                if (statusEl) statusEl.textContent = `HTTP ${res.status}`;
            } catch (e) {
                if (statusEl) statusEl.textContent = `Error: ${e.message}`;
            }
        }

        function renderMcpServers() {
            renderMcpServersInto('settings-mcp-server-list', { compact: true });
        }

        function renderMcpServersInto(containerId, { compact } = {}) {
            const list = document.getElementById(containerId);
            if (!list) return;
            const servers = loadMcpServers();
            list.innerHTML = '';
            if (servers.length === 0) {
                list.innerHTML = '<div class="text-gray-400 text-sm">No MCP servers configured.</div>';
                return;
            }

            servers.forEach((s) => {
                const card = document.createElement('div');
                card.className = compact
                    ? 'bg-gray-900/40 border border-gray-700 rounded-lg p-3 space-y-2'
                    : 'bg-gray-800 border border-gray-700 rounded-lg p-4 space-y-3';

                const toolsPreview = (() => {
                    try {
                        const tools = s.toolsJson ? JSON.parse(s.toolsJson) : [];
                        if (!Array.isArray(tools) || tools.length === 0) return '—';
                        return tools.slice(0, 8).join(', ') + (tools.length > 8 ? '…' : '');
                    } catch {
                        return 'Invalid tools JSON';
                    }
                })();

                card.innerHTML = `
                    <div class="flex items-start justify-between gap-3">
                        <div class="min-w-0">
                            <div class="font-semibold truncate">${sanitizeHtml(s.name)}</div>
                            <div class="text-xs text-gray-400 truncate">${sanitizeHtml(s.url)}</div>
                        </div>
                        <div class="flex gap-2 shrink-0">
                            <button class="bg-gray-700 hover:bg-gray-600 text-white px-2 py-1 rounded text-xs" type="button" id="${containerId}-mcp-test-${s.id}">Test</button>
                            <button class="bg-red-600 hover:bg-red-700 text-white px-2 py-1 rounded text-xs" type="button" id="${containerId}-mcp-del-${s.id}">Delete</button>
                        </div>
                    </div>
                    <div class="text-xs text-gray-300">Tools: <span class="text-gray-100">${sanitizeHtml(toolsPreview)}</span></div>
                    ${compact ? '' : `
                    <div class="grid grid-cols-1 md:grid-cols-2 gap-3">
                        <div>
                            <label class="block text-xs font-semibold text-gray-400 mb-1 uppercase">API Key</label>
                            <input type="password" value="${sanitizeHtml(s.apiKey || '')}" class="w-full bg-gray-700 text-sm rounded border border-gray-600 p-2 text-white outline-none focus:border-blue-500" id="${containerId}-mcp-apikey-${s.id}">
                        </div>
                        <div>
                            <label class="block text-xs font-semibold text-gray-400 mb-1 uppercase">Bearer Token</label>
                            <input type="password" value="${sanitizeHtml(s.token || '')}" class="w-full bg-gray-700 text-sm rounded border border-gray-600 p-2 text-white outline-none focus:border-blue-500" id="${containerId}-mcp-token-${s.id}">
                        </div>
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-gray-400 mb-1 uppercase">Extra Headers (JSON)</label>
                        <textarea rows="2" class="w-full bg-gray-700 text-sm rounded border border-gray-600 p-2 text-white outline-none focus:border-blue-500 font-mono" id="${containerId}-mcp-headers-${s.id}">${sanitizeHtml(s.headersJson || '{}')}</textarea>
                    </div>
                    <div>
                        <label class="block text-xs font-semibold text-gray-400 mb-1 uppercase">Tools (JSON array)</label>
                        <textarea rows="2" class="w-full bg-gray-700 text-sm rounded border border-gray-600 p-2 text-white outline-none focus:border-blue-500 font-mono" id="${containerId}-mcp-tools-${s.id}">${sanitizeHtml(s.toolsJson || '[]')}</textarea>
                    </div>
                    <div class="flex items-center justify-between">
                        <div class="text-xs text-gray-300">Status: <span class="text-gray-100" id="${containerId}-mcp-status-${s.id}">—</span></div>
                        <button class="bg-blue-600 hover:bg-blue-700 text-white px-3 py-1 rounded text-xs" type="button" id="${containerId}-mcp-save-${s.id}">Save</button>
                    </div>
                    `}
                `;
                list.appendChild(card);

                document.getElementById(`${containerId}-mcp-del-${s.id}`).onclick = () => deleteMcpServer(s.id);
                document.getElementById(`${containerId}-mcp-test-${s.id}`).onclick = () => testMcpServer(s.id, `${containerId}-mcp-status-${s.id}`);
                if (!compact) {
                    document.getElementById(`${containerId}-mcp-save-${s.id}`).onclick = () => {
                        updateMcpServer(s.id, {
                            apiKey: document.getElementById(`${containerId}-mcp-apikey-${s.id}`).value || '',
                            token: document.getElementById(`${containerId}-mcp-token-${s.id}`).value || '',
                            headersJson: document.getElementById(`${containerId}-mcp-headers-${s.id}`).value || '{}',
                            toolsJson: document.getElementById(`${containerId}-mcp-tools-${s.id}`).value || '[]'
                        });
                    };
                }
            });
        }

        // --- Provider & Models ---
        async function fetchModels({ quiet = true } = {}) {
            const apiKey = document.getElementById('chat-api-key')?.value || '';
            const baseUrl = document.getElementById('chat-base-url')?.value || '';
            if (!baseUrl) return;

            const res = await fetch('/api/proxy/models', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ apiKey, baseUrl })
            });
            if (!res.ok) {
                if (!quiet) alert(`Failed to fetch models: HTTP ${res.status}`);
                return;
            }
            const data = await res.json();
            const list = document.getElementById('model-list');
            if (!list) return;

            list.innerHTML = '';
            const models = data?.data || data;
            if (!Array.isArray(models)) return;

            const ids = models.map((m) => m?.id || m).filter(Boolean);
            ids.forEach((id) => {
                const opt = document.createElement('option');
                opt.value = id;
                list.appendChild(opt);
            });

            const modelEl = document.getElementById('chat-model');
            if (modelEl && !modelEl.value && ids[0]) {
                modelEl.value = ids[0];
                syncQuickModelFromSettings();
            }

            if (!quiet) alert(`Fetched ${ids.length} models.`);
        }

        const STANDARD_PROVIDERS = [
            { key: 'huggingface-router', name: 'HuggingFace Router', baseUrl: 'https://router.huggingface.co/v1' },
            { key: 'openai', name: 'OpenAI', baseUrl: 'https://api.openai.com/v1' },
            { key: 'openrouter', name: 'OpenRouter', baseUrl: 'https://openrouter.ai/api/v1' },
            { key: 'groq', name: 'Groq (OpenAI-compatible)', baseUrl: 'https://api.groq.com/openai/v1' },
            { key: 'together', name: 'Together', baseUrl: 'https://api.together.xyz/v1' },
            { key: 'fireworks', name: 'Fireworks', baseUrl: 'https://api.fireworks.ai/inference/v1' },
            { key: 'mistral', name: 'Mistral', baseUrl: 'https://api.mistral.ai/v1' },
            { key: 'deepseek', name: 'DeepSeek', baseUrl: 'https://api.deepseek.com/v1' },
        ];

        let providerCache = {}; // name -> { apiKey, baseUrl, model }
        let warnedProviderFallback = false;

        function initProviderPresets() {
            const presets = document.getElementById('provider-presets');
            if (!presets) return;
            presets.innerHTML = '<option value="">Select preset...</option>';
            STANDARD_PROVIDERS.forEach((p) => {
                const opt = document.createElement('option');
                opt.value = p.key;
                opt.innerText = `${p.name} — ${p.baseUrl}`;
                presets.appendChild(opt);
            });
        }

        function applyProviderPreset(key) {
            if (!key) return;
            const preset = STANDARD_PROVIDERS.find((p) => p.key === key);
            if (!preset) return;
            document.getElementById('chat-base-url').value = preset.baseUrl;
        }

        async function getActiveUserId() {
            const { data, error } = await supabase.auth.getUser();
            if (error) throw error;
            return data?.user?.id || null;
        }

        function loadProvidersFromLocalStorage() {
            const select = document.getElementById('saved-providers');
            const saved = JSON.parse(localStorage.getItem('chat_providers') || '{}');
            providerCache = saved;
            select.innerHTML = '<option value="">Select...</option>';
            Object.keys(saved).forEach((k) => {
                const opt = document.createElement('option');
                opt.value = k;
                opt.innerText = k;
                select.appendChild(opt);
            });

            const remembered = getRememberedProvider();
            if (remembered && providerCache[remembered]) {
                select.value = remembered;
                loadSelectedProvider(remembered);
            } else {
                const keys = Object.keys(providerCache);
                if (keys.length === 1) {
                    select.value = keys[0];
                    rememberActiveProvider(keys[0]);
                    loadSelectedProvider(keys[0]);
                }
            }
        }

        function rememberActiveProvider(name) {
            if (!name) {
                localStorage.removeItem('active_provider_name_v1');
                return;
            }
            localStorage.setItem('active_provider_name_v1', name);
        }

        function getRememberedProvider() {
            return localStorage.getItem('active_provider_name_v1') || '';
        }

        async function loadProviders() {
            try {
                const uid = await getActiveUserId();
                if (!uid) return loadProvidersFromLocalStorage();

                const { data, error } = await supabase
                    .from('provider_configs')
                    .select('name, api_key, base_url, model')
                    .eq('user_id', uid)
                    .order('name', { ascending: true });
                if (error) throw error;

                providerCache = {};
                (data || []).forEach((row) => {
                    providerCache[row.name] = { apiKey: row.api_key || '', baseUrl: row.base_url || '', model: row.model || '' };
                });

                const select = document.getElementById('saved-providers');
                select.innerHTML = '<option value="">Select...</option>';
                Object.keys(providerCache).forEach((k) => {
                    const opt = document.createElement('option');
                    opt.value = k;
                    opt.innerText = k;
                    select.appendChild(opt);
                });

                // Restore remembered provider selection if available
                const remembered = getRememberedProvider();
                if (remembered && providerCache[remembered]) {
                    select.value = remembered;
                    loadSelectedProvider(remembered);
                } else if (!select.value) {
                    const keys = Object.keys(providerCache);
                    if (keys.length === 1) {
                        select.value = keys[0];
                        rememberActiveProvider(keys[0]);
                        loadSelectedProvider(keys[0]);
                    }
                }
            } catch (e) {
                if (!warnedProviderFallback) {
                    warnedProviderFallback = true;
                    console.warn('Provider configs table missing or RLS blocked; falling back to localStorage.', e);
                }
                loadProvidersFromLocalStorage();
            }
        }

        async function saveProvider() {
            const name = prompt("Name:");
            if (!name) return;

            const config = {
                apiKey: document.getElementById('chat-api-key').value,
                baseUrl: document.getElementById('chat-base-url').value,
                model: document.getElementById('chat-model').value
            };

            try {
                const uid = await getActiveUserId();
                if (!uid) throw new Error('No active user session');

                const { error } = await supabase
                    .from('provider_configs')
                    .upsert(
                        { user_id: uid, name, api_key: config.apiKey, base_url: config.baseUrl, model: config.model },
                        { onConflict: 'user_id,name' }
                    );
                if (error) throw error;
                await loadProviders();
                document.getElementById('saved-providers').value = name;
                rememberActiveProvider(name);
            } catch (e) {
                // Fallback to local storage if table isn't available.
                const saved = JSON.parse(localStorage.getItem('chat_providers') || '{}');
                saved[name] = config;
                localStorage.setItem('chat_providers', JSON.stringify(saved));
                loadProvidersFromLocalStorage();
                document.getElementById('saved-providers').value = name;
                rememberActiveProvider(name);
            }
        }

        async function deleteProvider() {
            const name = document.getElementById('saved-providers').value;
            if (!name) return;
            if (!confirm("Delete?")) return;

            try {
                const uid = await getActiveUserId();
                if (!uid) throw new Error('No active user session');

                const { error } = await supabase
                    .from('provider_configs')
                    .delete()
                    .eq('user_id', uid)
                    .eq('name', name);
                if (error) throw error;
                await loadProviders();
            } catch (e) {
                const saved = JSON.parse(localStorage.getItem('chat_providers') || '{}');
                delete saved[name];
                localStorage.setItem('chat_providers', JSON.stringify(saved));
                loadProvidersFromLocalStorage();
            }
        }

        function loadSelectedProvider(name) {
            if (!name) return;
            rememberActiveProvider(name);
            const config = providerCache[name];
            if (config) {
                document.getElementById('chat-api-key').value = config.apiKey || '';
                document.getElementById('chat-base-url').value = config.baseUrl || '';
                document.getElementById('chat-model').value = config.model || '';
            }
        }

        // --- Notes (folders + markdown docs) ---
        let notesItems = []; // flat items from DB
        let activeNoteId = null;
        let activeFolderId = null;

        function setNotesStatus(msg) {
            const status = document.getElementById('notes-status');
            if (status) status.textContent = msg || '';
        }

        function getNotesInputs() {
            return {
                title: document.getElementById('notes-title'),
                editor: document.getElementById('notes-editor'),
                preview: document.getElementById('notes-preview'),
                tree: document.getElementById('notes-tree'),
            };
        }

        function renderNotesPreview() {
            const { editor, preview } = getNotesInputs();
            if (!editor || !preview) return;
            renderMarkdownInto(preview, editor.value || '');
        }

        function buildNotesTree() {
            const byParent = new Map();
            notesItems.forEach((item) => {
                const key = item.parent_id || 'root';
                if (!byParent.has(key)) byParent.set(key, []);
                byParent.get(key).push(item);
            });
            byParent.forEach((arr) => arr.sort((a, b) => (a.sort_order ?? 0) - (b.sort_order ?? 0) || (a.title || '').localeCompare(b.title || '')));
            return byParent;
        }

        function renderNotesTree() {
            const { tree } = getNotesInputs();
            if (!tree) return;
            const byParent = buildNotesTree();

            const makeNode = (item, depth) => {
                const row = document.createElement('div');
                row.className = 'flex items-center gap-2 py-1 px-2 rounded hover:bg-white/10';
                row.style.marginLeft = `${depth * 10}px`;

                const icon = document.createElement('span');
                icon.className = 'text-gray-400';
                icon.textContent = item.kind === 'folder' ? '▸' : '📝';

                const name = document.createElement('button');
                name.type = 'button';
                name.className = 'flex-grow text-left truncate';
                name.textContent = item.title || (item.kind === 'folder' ? 'Untitled folder' : 'Untitled note');
                name.onclick = () => {
                    if (item.kind === 'folder') {
                        activeFolderId = item.id;
                        // Keep active note selection if inside folder; otherwise clear note selection.
                        setNotesStatus(`Folder: ${item.title || 'Untitled'}`);
                        renderNotesTree();
                    } else {
                        openNote(item.id);
                    }
                };

                const actions = document.createElement('div');
                actions.className = 'flex gap-1 shrink-0 opacity-0 hover:opacity-100';

                const del = document.createElement('button');
                del.type = 'button';
                del.className = 'text-xs text-red-300 hover:text-red-200';
                del.textContent = 'Del';
                del.onclick = (e) => { e.stopPropagation(); deleteNoteItem(item.id); };

                actions.appendChild(del);

                row.appendChild(icon);
                row.appendChild(name);
                row.appendChild(actions);
                return row;
            };

            const renderBranch = (parentKey, depth) => {
                const items = byParent.get(parentKey) || [];
                const frag = document.createDocumentFragment();
                items.forEach((item) => {
                    const row = makeNode(item, depth);
                    if (item.id === activeFolderId || item.id === activeNoteId) row.classList.add('bg-white/10');
                    frag.appendChild(row);
                    if (item.kind === 'folder') {
                        // simple always-expanded tree
                        frag.appendChild(renderBranch(item.id, depth + 1));
                    }
                });
                return frag;
            };

            tree.innerHTML = '';
            tree.appendChild(renderBranch('root', 0));
        }

        async function refreshNotesTree() {
            try {
                const { data: { user } } = await supabase.auth.getUser();
                if (!user) return;
                const { data, error } = await supabase
                    .from('note_items')
                    .select('id,user_id,parent_id,kind,title,content,sort_order,updated_at')
                    .eq('user_id', user.id)
                    .order('sort_order', { ascending: true })
                    .order('title', { ascending: true });
                if (error) throw error;
                notesItems = data || [];
                renderNotesTree();
            } catch (e) {
                setNotesStatus('Notes table not configured yet.');
                console.warn('Notes load failed', e);
            }
        }

        function openNote(id) {
            const { title, editor } = getNotesInputs();
            const note = notesItems.find((n) => n.id === id && n.kind === 'note');
            if (!note || !title || !editor) return;
            activeNoteId = id;
            activeFolderId = note.parent_id || null;
            title.value = note.title || '';
            editor.value = note.content || '';
            renderNotesPreview();
            setNotesStatus(note.updated_at ? `Loaded (${new Date(note.updated_at).toLocaleString()})` : 'Loaded');
            renderNotesTree();
        }

        async function initNotes() {
            const { editor, preview } = getNotesInputs();
            if (!editor || !preview) return;

            applyNotesLayout();
            if (!localStorage.getItem('notes_mode_v1')) localStorage.setItem('notes_mode_v1', 'split');

            editor.addEventListener('keydown', async (e) => {
                if (e.key !== 'Enter' || e.shiftKey) return;

                const value = editor.value || '';
                const cursor = editor.selectionStart ?? value.length;
                const lineStart = value.lastIndexOf('\n', cursor - 1) + 1;
                const lineEnd = value.indexOf('\n', cursor);
                const end = lineEnd === -1 ? value.length : lineEnd;
                const line = value.slice(lineStart, end).trim();

                if (!line.toLowerCase().startsWith('@ai ')) return;
                e.preventDefault();

                const query = line.slice(4).trim();
                if (!query) return;
                await aiRespondIntoNotes(lineStart, end, query);
            });

            editor.addEventListener('input', () => {
                renderNotesPreview();
                setNotesStatus('Not saved');
            });
            const titleEl = document.getElementById('notes-title');
            if (titleEl) {
                titleEl.addEventListener('input', () => setNotesStatus('Not saved'));
            }

            await refreshNotesTree();
            // Auto-open most recently updated note if any
            const latest = notesItems.filter(i => i.kind === 'note').sort((a, b) => new Date(b.updated_at) - new Date(a.updated_at))[0];
            if (latest) openNote(latest.id);
        }

        async function createNotesFolder() {
            const name = prompt('Folder name:');
            if (!name) return;
            try {
                const { data: { user } } = await supabase.auth.getUser();
                if (!user) return;
                const { error } = await supabase.from('note_items').insert({
                    user_id: user.id,
                    parent_id: activeFolderId || null,
                    kind: 'folder',
                    title: name,
                    content: '',
                    sort_order: 0
                });
                if (error) throw error;
                await refreshNotesTree();
                setNotesStatus('Folder created');
            } catch (e) {
                setNotesStatus(`Create failed: ${e?.message || e}`);
            }
        }

        async function createNotesDoc() {
            const name = prompt('Note title:');
            if (!name) return;
            try {
                const { data: { user } } = await supabase.auth.getUser();
                if (!user) return;
                const { data, error } = await supabase.from('note_items').insert({
                    user_id: user.id,
                    parent_id: activeFolderId || null,
                    kind: 'note',
                    title: name,
                    content: '',
                    sort_order: 0
                }).select().single();
                if (error) throw error;
                await refreshNotesTree();
                if (data?.id) openNote(data.id);
                setNotesStatus('Note created');
            } catch (e) {
                setNotesStatus(`Create failed: ${e?.message || e}`);
            }
        }

        async function saveActiveNote() {
            const { title, editor } = getNotesInputs();
            if (!title || !editor) return;
            if (!activeNoteId) {
                await createNotesDoc();
                return;
            }
            try {
                const { error } = await supabase.from('note_items').update({
                    title: title.value || '',
                    content: editor.value || ''
                }).eq('id', activeNoteId);
                if (error) throw error;
                await refreshNotesTree();
                setNotesStatus(`Saved (${new Date().toLocaleString()})`);
            } catch (e) {
                setNotesStatus(`Save failed: ${e?.message || e}`);
            }
        }

        async function renameActiveNote() {
            if (!activeNoteId) return;
            const { title } = getNotesInputs();
            const name = prompt('New title:', title?.value || '');
            if (!name) return;
            if (title) title.value = name;
            await saveActiveNote();
        }

        async function deleteActiveNote() {
            if (!activeNoteId) return;
            await deleteNoteItem(activeNoteId);
        }

        async function deleteNoteItem(id) {
            const item = notesItems.find((n) => n.id === id);
            if (!item) return;
            if (!confirm(`Delete "${item.title || 'Untitled'}"? This deletes children too.`)) return;
            try {
                const { error } = await supabase.from('note_items').delete().eq('id', id);
                if (error) throw error;
                if (activeNoteId === id) activeNoteId = null;
                if (activeFolderId === id) activeFolderId = null;
                const { title, editor } = getNotesInputs();
                if (title) title.value = '';
                if (editor) editor.value = '';
                renderNotesPreview();
                await refreshNotesTree();
                setNotesStatus('Deleted');
            } catch (e) {
                setNotesStatus(`Delete failed: ${e?.message || e}`);
            }
        }

        let notesAiAbortController = null;

        function getProviderInputs() {
            return {
                apiKey: document.getElementById('chat-api-key')?.value || '',
                baseUrl: document.getElementById('chat-base-url')?.value || '',
                model: document.getElementById('chat-model')?.value || 'gpt-3.5-turbo',
            };
        }

        async function aiWriteNotes() {
            const { title, editor } = getNotesInputs();
            if (!editor) return;

            const instruction = prompt('Ask AI to write/edit this note (it will insert at your cursor):');
            if (!instruction) return;

            const provider = getProviderInputs();
            if (!provider.baseUrl) {
                alert('Set Base URL in Settings first.');
                return;
            }

            if (notesAiAbortController) notesAiAbortController.abort();
            notesAiAbortController = new AbortController();

            const currentTitle = title?.value || '(untitled)';
            const currentContent = editor.value || '';
            setNotesStatus('AI writing…');

            const messages = [
                {
                    role: 'system',
                    content: 'You are a helpful assistant writing concise, well-structured Markdown notes. Return Markdown only.'
                },
                {
                    role: 'user',
                    content:
                        `Note title: ${currentTitle}\n\n` +
                        `Current note:\n---\n${currentContent}\n---\n\n` +
                        `Task: ${instruction}\n\n` +
                        `Write the new content to insert at the cursor.`
                }
            ];

            try {
                const res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ messages, apiKey: provider.apiKey, baseUrl: provider.baseUrl, model: provider.model }),
                    signal: notesAiAbortController.signal
                });

                const reader = res.body.getReader();
                const decoder = new TextDecoder();
                let out = '';
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    out += decoder.decode(value);
                }

                const insertText = (out || '').trim();
                if (!insertText) {
                    setNotesStatus('AI returned empty output.');
                    return;
                }

                const start = editor.selectionStart ?? editor.value.length;
                const end = editor.selectionEnd ?? editor.value.length;
                const before = editor.value.slice(0, start);
                const after = editor.value.slice(end);
                const spacerLeft = before && !before.endsWith('\n') ? '\n' : '';
                const spacerRight = after && !insertText.endsWith('\n') ? '\n' : '';
                editor.value = `${before}${spacerLeft}${insertText}${spacerRight}${after}`;
                const cursor = (before + spacerLeft + insertText + spacerRight).length;
                editor.selectionStart = editor.selectionEnd = cursor;
                editor.dispatchEvent(new Event('input'));

                setNotesStatus(`AI inserted (${new Date().toLocaleTimeString()})`);
            } catch (e) {
                if (e?.name === 'AbortError') setNotesStatus('AI canceled.');
                else setNotesStatus(`AI failed: ${e?.message || e}`);
            } finally {
                notesAiAbortController = null;
            }
        }

        async function aiRespondIntoNotes(replaceStart, replaceEnd, query) {
            const { title, editor } = getNotesInputs();
            if (!editor) return;
            const provider = getProviderInputs();
            if (!provider.baseUrl) {
                alert('Set Base URL in Settings first.');
                return;
            }

            if (notesAiAbortController) notesAiAbortController.abort();
            notesAiAbortController = new AbortController();
            setNotesStatus('AI responding…');

            const messages = [
                { role: 'system', content: 'Reply conversationally and concisely. Plain text is fine.' },
                { role: 'user', content: query }
            ];

            try {
                const res = await fetch('/api/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ messages, apiKey: provider.apiKey, baseUrl: provider.baseUrl, model: provider.model }),
                    signal: notesAiAbortController.signal
                });
                const reader = res.body.getReader();
                const decoder = new TextDecoder();
                let out = '';
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    out += decoder.decode(value);
                }

                const answer = (out || '').trim() || '(no response)';
                const before = editor.value.slice(0, replaceStart);
                const after = editor.value.slice(replaceEnd);
                const block = `**@ai:** ${query}\n\n**AI:** ${answer}\n`;
                editor.value = before + block + after;
                const cursor = (before + block).length;
                editor.selectionStart = editor.selectionEnd = cursor;
                editor.dispatchEvent(new Event('input'));
                setNotesStatus(`AI inserted (${new Date().toLocaleTimeString()})`);
            } catch (e) {
                if (e?.name === 'AbortError') setNotesStatus('AI canceled.');
                else setNotesStatus(`AI failed: ${e?.message || e}`);
            } finally {
                notesAiAbortController = null;
            }
        }

        function applyNotesLayout() {
            const sidebar = document.getElementById('notes-sidebar');
            const editorPane = document.getElementById('notes-editor-pane');
            const previewPane = document.getElementById('notes-preview-pane');
            const main = document.getElementById('notes-main');
            const toggleEditorBtn = document.getElementById('notes-toggle-editor');
            const togglePreviewBtn = document.getElementById('notes-toggle-preview');
            if (!sidebar || !editorPane || !previewPane || !main) return;

            const sidebarHidden = localStorage.getItem('notes_sidebar_hidden_v1') === '1';
            const editorHidden = localStorage.getItem('notes_editor_hidden_v1') === '1';
            const previewHidden = localStorage.getItem('notes_preview_hidden_v1') === '1';
            const mode = localStorage.getItem('notes_mode_v1') || 'split';

            sidebar.classList.toggle('hidden', sidebarHidden);
            // Mode overrides per-pane hidden state (mode always wins)
            const effectiveEditorHidden =
                mode === 'preview' ? true :
                mode === 'edit' ? false :
                editorHidden;

            const effectivePreviewHidden =
                mode === 'edit' ? true :
                mode === 'preview' ? false :
                previewHidden;

            editorPane.classList.toggle('hidden', !!effectiveEditorHidden);
            previewPane.classList.toggle('hidden', !!effectivePreviewHidden);

            const editorVisible = !editorPane.classList.contains('hidden');
            const previewVisible = !previewPane.classList.contains('hidden');
            main.classList.toggle('lg:grid-cols-2', editorVisible && previewVisible);
            main.classList.toggle('lg:grid-cols-1', !(editorVisible && previewVisible));

            if (toggleEditorBtn) toggleEditorBtn.textContent = editorVisible ? 'Hide' : 'Show';
            if (togglePreviewBtn) togglePreviewBtn.textContent = previewVisible ? 'Hide' : 'Show';

            const btnSplit = document.getElementById('notes-mode-split');
            const btnEdit = document.getElementById('notes-mode-edit');
            const btnPreview = document.getElementById('notes-mode-preview');
            if (btnSplit) btnSplit.classList.toggle('bg-white/10', mode === 'split');
            if (btnEdit) btnEdit.classList.toggle('bg-white/10', mode === 'edit');
            if (btnPreview) btnPreview.classList.toggle('bg-white/10', mode === 'preview');

            // Ensure preview stays current when switching to preview-only
            if (previewVisible) renderNotesPreview();
        }

        function setNotesMode(mode) {
            const allowed = new Set(['split', 'edit', 'preview']);
            const next = allowed.has(mode) ? mode : 'split';
            localStorage.setItem('notes_mode_v1', next);
            applyNotesLayout();
        }

        function toggleNotesSidebar() {
            const key = 'notes_sidebar_hidden_v1';
            const next = localStorage.getItem(key) === '1' ? '0' : '1';
            localStorage.setItem(key, next);
            applyNotesLayout();
        }

        function toggleNotesPane(which) {
            const key = which === 'preview' ? 'notes_preview_hidden_v1' : 'notes_editor_hidden_v1';
            const next = localStorage.getItem(key) === '1' ? '0' : '1';
            localStorage.setItem(key, next);
            // Ensure at least one pane remains visible
            const editorHidden = localStorage.getItem('notes_editor_hidden_v1') === '1';
            const previewHidden = localStorage.getItem('notes_preview_hidden_v1') === '1';
            if (editorHidden && previewHidden) {
                localStorage.setItem('notes_editor_hidden_v1', '0');
            }
            applyNotesLayout();
        }

        init();
