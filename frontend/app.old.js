/* ═══════════════════════════════════════════════════════
   ClinicalPilot — Frontend Application Logic
   ═══════════════════════════════════════════════════════ */

const API = window.location.origin;
let currentSOAP = null;
let currentDebate = null;
let ws = null;

// ─── Classifiers Config ─────────────────────────────────
const CLASSIFIERS = [
    {
        id: 'lung',
        name: 'Lung Disease Classifier',
        icon: '🫁',
        description: 'AI-powered lung disease classification from chest X-rays',
        url: 'https://lung-disease-classification.streamlit.app/',
        color: '#3b82f6'
    },
    {
        id: 'chest',
        name: 'Chest Disease Classifier',
        icon: '🫀',
        description: 'Comprehensive chest disease detection and classification',
        url: 'https://caryaai.streamlit.app/',
        color: '#8b5cf6'
    },
    {
        id: 'retina',
        name: 'AI Retina Analyser',
        icon: '👁️',
        description: 'Diabetic retinopathy detection from retinal images',
        url: 'https://retinopathy-detection.streamlit.app/',
        color: '#10b981'
    },
    {
        id: 'skin',
        name: 'Skin Cancer Detector',
        icon: '🔬',
        description: 'Skin lesion analysis and melanoma classification',
        url: 'https://skincancer-detection.streamlit.app/',
        color: '#f59e0b'
    }
];

// ─── Sample Cases ────────────────────────────────────────
const SAMPLE_CASES = [
    `45-year-old male presenting to the ED with acute substernal chest pain radiating to his left arm for the past 2 hours. Associated diaphoresis and shortness of breath. 

PMH: Hypertension (10 years), Type 2 Diabetes Mellitus (5 years), Hyperlipidemia
Current Medications: Metformin 1000mg BID, Lisinopril 20mg daily, Atorvastatin 40mg daily, Aspirin 81mg daily

Vitals: BP 160/95 mmHg, HR 110 bpm, RR 22, Temp 98.6°F, SpO2 94% on RA
Labs: Troponin I 0.82 ng/mL (ref < 0.04), WBC 11.2 K/μL, Glucose 245 mg/dL, Creatinine 1.1 mg/dL
ECG: ST-elevation in leads V1-V4, reciprocal changes in II, III, aVF

Allergies: Sulfa drugs, Shellfish

The patient is alert, anxious, clutching his chest. Lungs clear bilaterally. S3 gallop noted. No peripheral edema.`,

    `72-year-old female brought in by EMS with sudden onset confusion, right-sided weakness, and slurred speech that started 45 minutes ago. Last known well at 10:00 AM.

PMH: Atrial fibrillation (on warfarin), CHF (EF 35%), CKD Stage 3
Medications: Warfarin 5mg daily, Metoprolol 50mg BID, Furosemide 40mg daily, Potassium 20mEq daily

Vitals: BP 185/105, HR 88 (irregularly irregular), RR 18, Temp 98.2°F, SpO2 96%
Labs: INR 2.8, Glucose 130, Creatinine 1.8, BUN 32
NIHSS: 14

GCS 13 (E3V4M6). Right facial droop, right arm drift, unable to lift right leg. Dysarthria present.
Allergies: Penicillin`
];

// ═══════════════════════════════════════════════════════
//  VIEW MANAGEMENT
// ═══════════════════════════════════════════════════════

function switchView(view) {
    document.querySelectorAll('.view-panel').forEach(el => el.classList.add('hidden'));
    document.querySelectorAll('.nav-btn').forEach(el => el.classList.remove('active'));

    document.getElementById(`view-${view}`).classList.remove('hidden');
    document.getElementById(`nav-${view === 'main' ? 'main' : view}`).classList.add('active');

    if (view === 'classifiers') renderClassifiers();
}

// ═══════════════════════════════════════════════════════
//  MAIN ANALYSIS
// ═══════════════════════════════════════════════════════

async function runAnalysis() {
    const input = document.getElementById('clinical-input').value.trim();
    if (!input) return showToast('Please enter clinical data', 'warning');

    setAnalyzing(true);
    showProgress(true);
    clearOutput();
    logAgent('system', 'Starting full analysis pipeline...');

    try {
        // Try WebSocket first for streaming
        if (await tryWebSocket(input)) return;

        // Fallback to REST
        logAgent('system', 'Using REST endpoint...');
        const response = await fetch(`${API}/api/analyze`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: input })
        });

        if (!response.ok) {
            const err = await response.json().catch(() => ({ detail: response.statusText }));
            throw new Error(err.detail || `HTTP ${response.status}`);
        }

        const data = await response.json();
        completeAllSteps();
        renderResults(data);
    } catch (err) {
        showError(err.message);
    } finally {
        setAnalyzing(false);
    }
}

function tryWebSocket(input) {
    return new Promise((resolve) => {
        const wsUrl = `${API.replace('http', 'ws')}/ws/analyze`;
        try {
            ws = new WebSocket(wsUrl);
        } catch {
            resolve(false);
            return;
        }

        const timeout = setTimeout(() => {
            ws.close();
            resolve(false);
        }, 3000);

        ws.onopen = () => {
            clearTimeout(timeout);
            ws.send(JSON.stringify({ text: input }));
            logAgent('system', 'WebSocket connected — streaming...');
        };

        ws.onmessage = (event) => {
            try {
                const msg = JSON.parse(event.data);
                handleWSMessage(msg);
                if (msg.type === 'complete') {
                    setAnalyzing(false);
                    resolve(true);
                }
            } catch { /* ignore non-JSON */ }
        };

        ws.onerror = () => {
            clearTimeout(timeout);
            resolve(false);
        };

        ws.onclose = () => { resolve(false); };
    });
}

function handleWSMessage(msg) {
    const text = msg.detail || msg.stage || msg.message || '';
    switch (msg.type) {
        case 'status':
            logAgent('pipeline', text);
            // Advance progress steps based on stage or text content
            const s = (msg.stage || text).toLowerCase();
            if (s.includes('pars')) updateStep('parsing', 'done');
            if (s.includes('agent')) { updateStep('parsing', 'done'); updateStep('agents', 'active'); }
            if (s.includes('debate') || s.includes('critic')) { updateStep('agents', 'done'); updateStep('debate', 'active'); }
            if (s.includes('synth')) { updateStep('debate', 'done'); updateStep('synthesis', 'active'); }
            if (s.includes('safety') || s.includes('panel')) { updateStep('synthesis', 'done'); updateStep('safety_panel', 'active'); }
            break;
        case 'agent_result':
            logAgent('pipeline', `${msg.agent || 'Agent'} completed`);
            break;
        case 'complete':
            completeAllSteps();
            // Backend sends soap/debate/med_error_panel directly on msg
            renderResults(msg);
            break;
        case 'error':
            showError(msg.message || text);
            break;
    }
}

// ═══════════════════════════════════════════════════════
//  EMERGENCY MODE
// ═══════════════════════════════════════════════════════

async function runEmergency() {
    const input = document.getElementById('emergency-input').value.trim();
    if (!input) return showToast('Describe the emergency', 'warning');

    const btn = document.getElementById('btn-emergency');
    const icon = document.getElementById('emergency-icon');
    const text = document.getElementById('emergency-text');
    btn.disabled = true;
    icon.innerHTML = '<span class="spinner"></span>';
    text.textContent = 'TRIAGING...';

    const startTime = performance.now();

    try {
        const response = await fetch(`${API}/api/emergency`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ text: input })
        });

        if (!response.ok) {
            const err = await response.json().catch(() => ({ detail: response.statusText }));
            throw new Error(err.detail || `HTTP ${response.status}`);
        }

        const data = await response.json();
        const latency = ((performance.now() - startTime) / 1000).toFixed(1);
        renderEmergencyResult(data, latency);
    } catch (err) {
        showToast(`Emergency error: ${err.message}`, 'error');
    } finally {
        btn.disabled = false;
        icon.textContent = '🚨';
        text.textContent = 'TRIAGE NOW';
    }
}

function renderEmergencyResult(data, latency) {
    const output = document.getElementById('emergency-output');
    output.classList.remove('hidden');

    // API returns { emergency: { ... } }
    const em = data.emergency || data;

    // ESI Score
    const esi = em.esi_score || '?';
    const esiEl = document.getElementById('esi-score');
    esiEl.textContent = esi;
    esiEl.className = `text-4xl font-bold esi-${esi}`;

    document.getElementById('emergency-latency').textContent = `${latency}s response time`;

    // Top Differentials
    const diffEl = document.getElementById('emergency-differentials');
    diffEl.innerHTML = '';
    const diffs = em.top_differentials || [];
    diffs.forEach(d => {
        const name = typeof d === 'string' ? d : d.diagnosis || d.name;
        const conf = typeof d === 'string' ? '' : d.likelihood || d.confidence || '';
        diffEl.innerHTML += `
            <div class="flex items-center justify-between text-sm">
                <span class="text-white">${escapeHtml(name)}</span>
                ${conf ? `<span class="text-gray-400">${escapeHtml(String(conf))}</span>` : ''}
            </div>`;
    });

    // Red Flags
    const flagsEl = document.getElementById('emergency-red-flags');
    flagsEl.innerHTML = '';
    const flags = em.red_flags || [];
    flags.forEach(f => {
        flagsEl.innerHTML += `<li class="text-red-300">⚠️ ${escapeHtml(f)}</li>`;
    });

    // Call to Action
    document.getElementById('emergency-action').textContent =
        em.call_to_action || 'Immediate medical evaluation required';

    // Safety Flags
    const safetyFlags = em.safety_flags || [];
    const safetySection = document.getElementById('emergency-safety');
    if (safetyFlags.length > 0) {
        safetySection.classList.remove('hidden');
        const safetyList = document.getElementById('emergency-safety-list');
        safetyList.innerHTML = '';
        safetyFlags.forEach(f => {
            const txt = typeof f === 'string' ? f : f.description || f.flag;
            safetyList.innerHTML += `<li class="text-orange-300">💊 ${escapeHtml(txt)}</li>`;
        });
    } else {
        safetySection.classList.add('hidden');
    }
}

// ═══════════════════════════════════════════════════════
//  FILE UPLOADS
// ═══════════════════════════════════════════════════════

async function handleFileUpload(input) {
    const file = input.files[0];
    if (!file) return;

    const statusEl = document.getElementById('file-status');
    statusEl.textContent = `Uploading ${file.name}...`;

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch(`${API}/api/upload/ehr`, {
            method: 'POST',
            body: formData
        });
        if (!response.ok) throw new Error('Upload failed');
        const data = await response.json();

        // Populate input with parsed context summary
        if (data.patient_context) {
            const ctx = data.patient_context;
            let summary = '';
            if (ctx.age) summary += `${ctx.age}-year-old ${ctx.gender || ''}\n`;
            if (ctx.conditions?.length) summary += `Conditions: ${ctx.conditions.map(c => c.name || c).join(', ')}\n`;
            if (ctx.medications?.length) summary += `Medications: ${ctx.medications.map(m => m.name || m).join(', ')}\n`;
            if (ctx.current_prompt) summary += `\n${ctx.current_prompt}`;
            document.getElementById('clinical-input').value = summary.trim();
        }

        statusEl.textContent = `✅ ${file.name} parsed successfully`;
        logAgent('upload', `EHR file parsed: ${file.name}`);
    } catch (err) {
        statusEl.textContent = `❌ ${err.message}`;
    }
    input.value = '';
}

async function handleFhirUpload(input) {
    const file = input.files[0];
    if (!file) return;

    const statusEl = document.getElementById('file-status');
    statusEl.textContent = `Uploading FHIR bundle...`;

    const text = await file.text();
    try {
        const response = await fetch(`${API}/api/upload/fhir`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: text
        });
        if (!response.ok) throw new Error('FHIR upload failed');
        const data = await response.json();

        if (data.patient_context) {
            const ctx = data.patient_context;
            let summary = '';
            if (ctx.age) summary += `${ctx.age}-year-old ${ctx.gender || ''}\n`;
            if (ctx.conditions?.length) summary += `Conditions: ${ctx.conditions.map(c => c.name || c).join(', ')}\n`;
            if (ctx.medications?.length) summary += `Medications: ${ctx.medications.map(m => m.name || m).join(', ')}\n`;
            document.getElementById('clinical-input').value = summary.trim();
        }

        statusEl.textContent = `✅ FHIR bundle loaded`;
        logAgent('upload', 'FHIR bundle parsed successfully');
    } catch (err) {
        statusEl.textContent = `❌ ${err.message}`;
    }
    input.value = '';
}

// ═══════════════════════════════════════════════════════
//  RENDER RESULTS
// ═══════════════════════════════════════════════════════

function renderResults(data) {
    if (!data) { showError('No data received'); return; }
    const soap = data.soap || data.soap_note || data;
    const debate = data.debate || data.debate_state || {};
    const medErrors = data.med_error_panel || data.safety_panel || {};

    currentSOAP = soap;
    currentDebate = debate;

    // SOAP fields
    document.getElementById('soap-subjective').textContent = soap.subjective || 'N/A';
    document.getElementById('soap-objective').textContent = soap.objective || 'N/A';
    document.getElementById('soap-assessment').textContent = soap.assessment || 'N/A';
    document.getElementById('soap-plan').textContent = soap.plan || 'N/A';

    // Confidence badge (field is 'uncertainty' in the model)
    const conf = (soap.uncertainty || soap.confidence || 'medium').toLowerCase();
    const badge = document.getElementById('confidence-badge');
    badge.textContent = `${conf.charAt(0).toUpperCase() + conf.slice(1)} Confidence`;
    badge.className = `text-xs px-2 py-1 rounded-full confidence-${conf}`;

    // Differentials
    renderDifferentials(soap.differentials || []);

    // Risk Scores
    if (soap.risk_scores && Object.keys(soap.risk_scores).length > 0) {
        document.getElementById('risk-scores-section').classList.remove('hidden');
        const list = document.getElementById('risk-scores-list');
        list.innerHTML = '';
        for (const [name, value] of Object.entries(soap.risk_scores)) {
            list.innerHTML += `
                <div class="flex items-center justify-between text-sm bg-gray-800/50 rounded-lg px-3 py-2">
                    <span class="text-gray-300">${escapeHtml(name)}</span>
                    <span class="font-mono text-blue-400">${escapeHtml(String(value))}</span>
                </div>`;
        }
    }

    // Citations
    if (soap.citations && soap.citations.length > 0) {
        document.getElementById('citations-section').classList.remove('hidden');
        const citList = document.getElementById('citations-list');
        citList.innerHTML = '';
        soap.citations.forEach(c => {
            citList.innerHTML += `<li class="text-gray-400">${escapeHtml(c)}</li>`;
        });
    }

    // Debate Summary
    document.getElementById('debate-summary').textContent =
        soap.debate_summary || debate.summary || 'No debate summary available.';

    // Dissent Log
    const dissentEl = document.getElementById('dissent-log');
    dissentEl.innerHTML = '';
    const dissents = soap.dissent_log || debate.dissent_log || [];
    dissents.forEach(d => {
        dissentEl.innerHTML += `<span class="dissent-tag">${escapeHtml(d)}</span> `;
    });

    // Patient Context (sidebar)
    renderPatientCard(data.patient_context || {});

    // Safety Panel (sidebar)
    renderSafetyPanel(medErrors);

    // Metadata
    renderMetadata(data);

    // Show output sections
    document.getElementById('soap-output').classList.remove('hidden');
    logAgent('system', '✅ Analysis complete — results rendered');
}

function renderDifferentials(diffs) {
    const container = document.getElementById('differentials-list');
    container.innerHTML = '';

    // Map confidence strings to numeric values for bar display
    const confMap = { high: 85, medium: 55, low: 25 };
    const likelihoodMap = { 'most likely': 90, 'likely': 75, 'high': 85, 'moderate': 55, 'medium': 55, 'possible': 40, 'low': 25, 'unlikely': 15 };

    diffs.forEach((d, i) => {
        const name = d.diagnosis || d.name || d;
        const reasoning = d.reasoning || d.rationale || '';
        const likelihood = (d.likelihood || '').toLowerCase();
        const confidence = (d.confidence || 'medium').toLowerCase();

        // Use likelihood first, then confidence, then fallback
        let pct = likelihoodMap[likelihood] || confMap[confidence] || 50;
        // Decrease slightly for lower-ranked items
        pct = Math.max(10, pct - (i * 5));

        const colors = ['#3b82f6', '#8b5cf6', '#10b981', '#f59e0b', '#ef4444'];
        const color = colors[i % colors.length];
        const label = d.likelihood || confidence;

        container.innerHTML += `
            <div class="diff-card">
                <div class="flex items-center justify-between mb-2">
                    <span class="font-medium text-sm">${i + 1}. ${escapeHtml(typeof name === 'string' ? name : String(name))}</span>
                    <span class="text-xs font-mono" style="color: ${color}">${escapeHtml(label)}</span>
                </div>
                <div class="diff-bar">
                    <div class="diff-bar-fill" style="width: ${pct}%; background: ${color}"></div>
                </div>
                ${reasoning ? `<p class="text-xs text-gray-500 mt-2">${escapeHtml(reasoning)}</p>` : ''}
                ${d.supporting_evidence?.length ? `<p class="text-xs text-cyan-600 mt-1">${d.supporting_evidence.map(e => escapeHtml(e)).join(' | ')}</p>` : ''}
            </div>`;
    });
}

function renderPatientCard(ctx) {
    if (!ctx || Object.keys(ctx).length === 0) return;
    const card = document.getElementById('patient-card');
    card.classList.remove('hidden');
    const info = document.getElementById('patient-info');
    info.innerHTML = '';

    const fields = [
        { label: 'Age', value: ctx.age },
        { label: 'Gender', value: ctx.gender },
        { label: 'Conditions', value: ctx.conditions?.map(c => c.name || c).join(', ') },
        { label: 'Medications', value: ctx.medications?.map(m => m.name || m).join(', ') },
        { label: 'Allergies', value: ctx.allergies?.map(a => a.substance || a).join(', ') },
    ];

    fields.forEach(f => {
        if (f.value) {
            info.innerHTML += `
                <div class="flex gap-2">
                    <span class="text-gray-500 min-w-20">${f.label}:</span>
                    <span class="text-gray-300">${escapeHtml(String(f.value))}</span>
                </div>`;
        }
    });
}

function renderSafetyPanel(panel) {
    if (!panel || Object.keys(panel).length === 0) return;

    const container = document.getElementById('safety-panel');
    container.classList.remove('hidden');
    const content = document.getElementById('safety-content');
    content.innerHTML = '';

    // Drug Interactions (backend field: drug_interactions)
    const interactions = panel.drug_interactions || panel.interactions || [];
    if (interactions.length > 0) {
        content.innerHTML += `<div class="text-xs font-semibold text-red-400 mb-1">Drug Interactions</div>`;
        interactions.forEach(i => {
            const sev = (i.severity || 'moderate').toLowerCase();
            const cls = sev === 'contraindicated' || sev === 'major' || sev === 'severe' ? '' : sev === 'moderate' ? 'warning' : 'info';
            content.innerHTML += `
                <div class="safety-item ${cls}">
                    <strong>${escapeHtml(i.drug_a || '')} × ${escapeHtml(i.drug_b || '')}</strong>
                    <span class="text-xs ml-2 opacity-75">${escapeHtml(i.severity || '')}</span>
                    <p class="mt-1 opacity-75">${escapeHtml(i.description || '')}</p>
                    ${i.recommendation ? `<p class="mt-1 text-xs text-green-400">→ ${escapeHtml(i.recommendation)}</p>` : ''}
                </div>`;
        });
    }

    // Contraindications
    const contras = panel.contraindications || [];
    if (contras.length > 0) {
        content.innerHTML += `<div class="text-xs font-semibold text-orange-400 mb-1 mt-3">Contraindications</div>`;
        contras.forEach(c => {
            content.innerHTML += `
                <div class="safety-item warning">
                    <strong>${escapeHtml(c.drug || '')}</strong> — ${escapeHtml(c.disease || c.condition || '')}
                    <p class="mt-1 opacity-75">${escapeHtml(c.description || '')}</p>
                    ${c.recommendation ? `<p class="mt-1 text-xs text-green-400">→ ${escapeHtml(c.recommendation)}</p>` : ''}
                </div>`;
        });
    }

    // Dosing Alerts
    const dosing = panel.dosing_alerts || [];
    if (dosing.length > 0) {
        content.innerHTML += `<div class="text-xs font-semibold text-yellow-400 mb-1 mt-3">Dosing Alerts</div>`;
        dosing.forEach(d => {
            content.innerHTML += `
                <div class="safety-item warning">
                    <strong>${escapeHtml(d.drug || '')}</strong> <span class="text-xs opacity-50">[${escapeHtml(d.alert_type || '')}]</span>
                    <p class="mt-1 opacity-75">${escapeHtml(d.description || d.message || d.alert || '')}</p>
                    ${d.recommendation ? `<p class="mt-1 text-xs text-green-400">→ ${escapeHtml(d.recommendation)}</p>` : ''}
                </div>`;
        });
    }

    // Population Flags
    const popFlags = panel.population_flags || [];
    if (popFlags.length > 0) {
        content.innerHTML += `<div class="text-xs font-semibold text-blue-400 mb-1 mt-3">Population Flags</div>`;
        popFlags.forEach(p => {
            content.innerHTML += `
                <div class="safety-item info">
                    <strong>${escapeHtml(p.drug || '')}</strong> — ${escapeHtml(p.population || '')}
                    <p class="mt-1 opacity-75">${escapeHtml(p.description || p.flag || String(p))}</p>
                    ${p.recommendation ? `<p class="mt-1 text-xs text-green-400">→ ${escapeHtml(p.recommendation)}</p>` : ''}
                </div>`;
        });
    }

    // Overall summary
    if (panel.summary) {
        content.innerHTML += `
            <div class="mt-3 text-xs text-gray-400 italic border-t border-gray-800 pt-2">
                ${escapeHtml(panel.summary)}
            </div>`;
    }
}

function renderMetadata(data) {
    const card = document.getElementById('metadata-card');
    card.classList.remove('hidden');
    const info = document.getElementById('metadata-info');
    info.innerHTML = '';

    const soap = data.soap || data.soap_note || data;
    const debate = data.debate || data.debate_state || {};

    const items = [
        { label: 'Debate Rounds', value: debate.round_number || debate.rounds_completed },
        { label: 'Consensus', value: debate.final_consensus != null ? (debate.final_consensus ? 'Yes' : 'No — flagged for human review') : null },
        { label: 'Model', value: soap.model_used || data.model },
        { label: 'Latency', value: soap.latency_ms ? `${(soap.latency_ms / 1000).toFixed(1)}s` : null },
        { label: 'Tokens', value: soap.total_tokens || null },
    ];

    items.forEach(i => {
        if (i.value != null) {
            info.innerHTML += `
                <div class="flex justify-between">
                    <span class="text-gray-600">${i.label}</span>
                    <span class="text-gray-400">${escapeHtml(String(i.value))}</span>
                </div>`;
        }
    });
}

// ═══════════════════════════════════════════════════════
//  CLASSIFIERS
// ═══════════════════════════════════════════════════════

function renderClassifiers() {
    const container = document.getElementById('classifier-cards');
    if (container.children.length > 0) return; // already rendered

    CLASSIFIERS.forEach(clf => {
        container.innerHTML += `
            <div class="classifier-card" onclick="openClassifier('${clf.id}')" style="border-left: 3px solid ${clf.color}">
                <div class="flex items-center gap-3 mb-3">
                    <span class="text-3xl">${clf.icon}</span>
                    <div>
                        <h3 class="font-semibold text-white">${clf.name}</h3>
                        <p class="text-xs text-gray-400">${clf.description}</p>
                    </div>
                </div>
                <div class="flex gap-2">
                    <span class="text-xs px-2 py-1 bg-gray-800 rounded-lg text-gray-400">Click to embed</span>
                    <a href="${clf.url}" target="_blank" onclick="event.stopPropagation()"
                        class="text-xs px-2 py-1 bg-gray-800 rounded-lg text-blue-400 hover:text-blue-300">
                        ↗ Open external
                    </a>
                </div>
            </div>`;
    });
}

function openClassifier(id) {
    const clf = CLASSIFIERS.find(c => c.id === id);
    if (!clf) return;

    document.getElementById('classifier-cards').classList.add('hidden');
    document.getElementById('classifier-embed').classList.remove('hidden');
    document.getElementById('classifier-title').textContent = `${clf.icon} ${clf.name}`;
    document.getElementById('classifier-external-link').href = clf.url;

    const iframe = document.getElementById('classifier-iframe');
    iframe.src = clf.url;
}

function closeClassifier() {
    document.getElementById('classifier-embed').classList.add('hidden');
    document.getElementById('classifier-cards').classList.remove('hidden');
    document.getElementById('classifier-iframe').src = '';
}

// ═══════════════════════════════════════════════════════
//  HUMAN-IN-THE-LOOP
// ═══════════════════════════════════════════════════════

async function submitFeedback() {
    const feedback = document.getElementById('human-feedback').value.trim();
    if (!feedback) return showToast('Enter feedback first', 'warning');
    if (!currentSOAP) return showToast('Run an analysis first', 'warning');

    logAgent('human', `Doctor feedback: "${feedback.substring(0, 60)}..."`);

    try {
        const response = await fetch(`${API}/api/human-feedback`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                original_soap: currentSOAP,
                feedback: feedback
            })
        });

        if (!response.ok) throw new Error('Feedback submission failed');
        const data = await response.json();

        showToast('Re-analysis with feedback complete', 'success');
        if (data.soap || data.soap_note) {
            renderResults(data);
        }
        document.getElementById('human-feedback').value = '';
    } catch (err) {
        showToast(`Feedback error: ${err.message}`, 'error');
    }
}

function enableEdit() {
    document.querySelectorAll('.soap-content').forEach(el => {
        el.contentEditable = el.contentEditable === 'true' ? 'false' : 'true';
    });
    showToast('SOAP fields are now editable — use "Re-analyze with Feedback" to submit changes', 'info');
}

function copySOAP() {
    if (!currentSOAP) return;
    const text = `SOAP Note — ClinicalPilot\n${'═'.repeat(40)}\n\nS — Subjective:\n${currentSOAP.subjective || 'N/A'}\n\nO — Objective:\n${currentSOAP.objective || 'N/A'}\n\nA — Assessment:\n${currentSOAP.assessment || 'N/A'}\n\nP — Plan:\n${currentSOAP.plan || 'N/A'}\n\nConfidence: ${currentSOAP.confidence || 'N/A'}`;
    navigator.clipboard.writeText(text).then(() => showToast('SOAP note copied to clipboard', 'success'));
}

// ═══════════════════════════════════════════════════════
//  UI HELPERS
// ═══════════════════════════════════════════════════════

function setAnalyzing(active) {
    const btn = document.getElementById('btn-analyze');
    const icon = document.getElementById('analyze-icon');
    const text = document.getElementById('analyze-text');
    btn.disabled = active;
    icon.innerHTML = active ? '<span class="spinner"></span>' : '🔬';
    text.textContent = active ? 'Analyzing...' : 'Run Full Analysis';
}

function showProgress(show) {
    const el = document.getElementById('pipeline-progress');
    if (show) {
        el.classList.remove('hidden');
        document.querySelectorAll('.progress-step').forEach(step => {
            step.classList.remove('active', 'done', 'error');
            step.querySelector('.step-icon').textContent = '⏳';
        });
        updateStep('parsing', 'active');
    } else {
        el.classList.add('hidden');
    }
}

function updateStep(name, status) {
    const step = document.querySelector(`.progress-step[data-step="${name}"]`);
    if (!step) return;
    step.classList.remove('active', 'done', 'error');
    step.classList.add(status);
    const icon = step.querySelector('.step-icon');
    if (status === 'active') { icon.innerHTML = '<span class="spinner"></span>'; step.classList.add('pulse'); }
    else if (status === 'done') { icon.textContent = '✅'; step.classList.remove('pulse'); }
    else if (status === 'error') { icon.textContent = '❌'; step.classList.remove('pulse'); }
}

function completeAllSteps() {
    ['parsing', 'agents', 'debate', 'synthesis', 'safety_panel'].forEach(s => updateStep(s, 'done'));
}

function clearOutput() {
    document.getElementById('soap-output').classList.add('hidden');
    document.getElementById('patient-card').classList.add('hidden');
    document.getElementById('safety-panel').classList.add('hidden');
    document.getElementById('metadata-card').classList.add('hidden');
    document.getElementById('risk-scores-section').classList.add('hidden');
    document.getElementById('citations-section').classList.add('hidden');
    currentSOAP = null;
    currentDebate = null;
}

function clearAll() {
    document.getElementById('clinical-input').value = '';
    document.getElementById('file-status').textContent = '';
    document.getElementById('pipeline-progress').classList.add('hidden');
    clearOutput();
    document.getElementById('agent-log').innerHTML = '<p class="italic">Waiting for analysis...</p>';
}

function loadSampleCase() {
    const idx = Math.floor(Math.random() * SAMPLE_CASES.length);
    document.getElementById('clinical-input').value = SAMPLE_CASES[idx];
    showToast('Sample case loaded', 'info');
}

function logAgent(source, message) {
    const log = document.getElementById('agent-log');
    const first = log.querySelector('.italic');
    if (first) first.remove();

    const time = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
    const colors = {
        system: 'text-blue-400',
        pipeline: 'text-cyan-400',
        human: 'text-purple-400',
        upload: 'text-green-400',
        error: 'text-red-400'
    };

    log.innerHTML += `
        <div class="agent-log-entry">
            <span class="text-gray-600">${time}</span>
            <span class="${colors[source] || 'text-gray-400'}">[${source}]</span>
            <span class="text-gray-300">${escapeHtml(message)}</span>
        </div>`;
    log.scrollTop = log.scrollHeight;
}

function showError(msg) {
    logAgent('error', msg);
    showToast(msg, 'error');
    document.querySelectorAll('.progress-step.active').forEach(s => updateStep(s.dataset.step, 'error'));
}

function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    const bg = { info: 'bg-blue-900 border-blue-700', success: 'bg-green-900 border-green-700', warning: 'bg-yellow-900 border-yellow-700', error: 'bg-red-900 border-red-700' };
    toast.className = `fixed bottom-4 right-4 px-5 py-3 rounded-xl border ${bg[type]} text-white text-sm z-50 shadow-lg`;
    toast.style.animation = 'fadeIn 0.2s ease-out';
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => { toast.style.opacity = '0'; toast.style.transition = 'opacity 0.3s'; setTimeout(() => toast.remove(), 300); }, 3000);
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ═══════════════════════════════════════════════════════
//  INITIALIZATION
// ═══════════════════════════════════════════════════════

document.addEventListener('DOMContentLoaded', () => {
    // Health check
    fetch(`${API}/api/health`)
        .then(r => r.json())
        .then(data => {
            document.getElementById('status-indicator').title = `Connected — ${data.status || 'ok'}`;
            document.getElementById('status-indicator').className = 'w-2 h-2 rounded-full bg-green-500 inline-block';
        })
        .catch(() => {
            document.getElementById('status-indicator').className = 'w-2 h-2 rounded-full bg-red-500 inline-block';
            document.getElementById('status-indicator').title = 'Backend not reachable';
        });

    // Keyboard shortcut: Ctrl+Enter to analyze
    document.getElementById('clinical-input').addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            e.preventDefault();
            runAnalysis();
        }
    });

    document.getElementById('emergency-input').addEventListener('keydown', (e) => {
        if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
            e.preventDefault();
            runEmergency();
        }
    });
});
