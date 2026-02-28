#!/bin/bash
set -e
cd /Users/lakshya/Documents/Workspace/clinicalpilot
source venv/bin/activate

echo "============================================"
echo " ClinicalPilot Smoke Test Suite"
echo "============================================"

# 1. Health check
echo ""
echo "=== TEST 1: Health Check ==="
curl -sf http://localhost:8000/api/health | python3 -m json.tool
echo "PASS: Health check OK"

# 2. Full analysis (timed)
echo ""
echo "=== TEST 2: Full Analysis Pipeline ==="
echo "Sending request... (may take 30-60s)"
START=$(date +%s)
curl -sf -X POST http://localhost:8000/api/analyze \
  -H "Content-Type: application/json" \
  -d '{"text": "65-year-old male with HTN and Type 2 Diabetes. Current medications: Metformin 1000mg BID, Lisinopril 20mg daily, Potassium 20mEq daily. Allergic to Penicillin. BP 145/92, HR 78. HbA1c 8.2, Creatinine 1.4. Presenting with increased fatigue and dizziness."}' \
  -o /tmp/cp_analysis.json
END=$(date +%s)
ELAPSED=$((END - START))
echo "Completed in ${ELAPSED}s"

python3 << 'PYEOF'
import json, sys
with open("/tmp/cp_analysis.json") as f:
    d = json.load(f)

soap = d.get("soap", {})
debate = d.get("debate", {})
med = d.get("med_error_panel", {})

errors = []

# Check SOAP sections
for field in ["subjective", "objective", "assessment", "plan"]:
    val = soap.get(field, "")
    if not val:
        errors.append(f"SOAP {field} is EMPTY")
    else:
        print(f"  SOAP {field}: {val[:100]}...")

# Differentials
diffs = soap.get("differentials", [])
print(f"  Differentials: {len(diffs)}")
for dd in diffs:
    print(f"    - {dd['diagnosis']} ({dd.get('confidence','?')}, {dd.get('likelihood','?')})")
if len(diffs) < 2:
    errors.append(f"Only {len(diffs)} differentials (need >= 2)")

# Citations
cites = soap.get("citations", [])
print(f"  Citations: {len(cites)}")

# Safety
flags = soap.get("safety_flags", [])
print(f"  Safety flags: {len(flags)}")
for sf in flags:
    print(f"    - {sf[:80]}")

# Debate
print(f"  Debate rounds: {debate.get('round_number')}")
print(f"  Consensus: {debate.get('final_consensus')}")
print(f"  Model: {soap.get('model_used')}")
print(f"  Latency: {soap.get('latency_ms')}ms")
print(f"  Tokens: {soap.get('total_tokens')}")

# Med error panel
print(f"  Drug interactions: {len(med.get('drug_interactions', []))}")
for i in med.get("drug_interactions", []):
    print(f"    - {i['drug_a']} x {i['drug_b']} [{i['severity']}]")
print(f"  Contraindications: {len(med.get('contraindications', []))}")
print(f"  Dosing alerts: {len(med.get('dosing_alerts', []))}")
print(f"  Population flags: {len(med.get('population_flags', []))}")
print(f"  Summary: {med.get('summary', '')[:120]}")

if errors:
    print(f"\nFAILED: {len(errors)} issues:")
    for e in errors:
        print(f"  X {e}")
    sys.exit(1)
else:
    print("\nPASS: Full analysis — all fields present")
PYEOF

# 3. Emergency mode
echo ""
echo "=== TEST 3: Emergency Mode ==="
START=$(date +%s)
curl -sf -X POST http://localhost:8000/api/emergency \
  -H "Content-Type: application/json" \
  -d '{"text": "55-year-old male with sudden onset chest pain, diaphoresis, BP 90/60, HR 130. PMH: DM2, CAD. On aspirin, metformin."}' \
  -o /tmp/cp_emergency.json
END=$(date +%s)
echo "Completed in $((END - START))s"

python3 << 'PYEOF'
import json
with open("/tmp/cp_emergency.json") as f:
    d = json.load(f)
em = d.get("emergency", {})
print(f"  ESI Score: {em.get('esi_score', '?')}")
print(f"  Differentials: {len(em.get('top_differentials', []))}")
for dd in em.get("top_differentials", []):
    print(f"    - {dd.get('diagnosis','?')}")
print(f"  Red flags: {len(em.get('red_flags', []))}")
print(f"  Call to action: {em.get('call_to_action', '')[:100]}")
print(f"  Safety flags: {len(em.get('safety_flags', []))}")
print(f"  Latency: {em.get('latency_ms', '?')}ms")
print("PASS: Emergency mode OK")
PYEOF

# 4. Safety check API
echo ""
echo "=== TEST 4: Drug Safety Check ==="
curl -sf "http://localhost:8000/api/safety-check?drugs=metformin,lisinopril,potassium" -o /tmp/cp_safety.json
python3 << 'PYEOF'
import json
with open("/tmp/cp_safety.json") as f:
    d = json.load(f)
print(f"  RxNorm interactions: {d.get('rxnorm_interactions', 'N/A')}")
print(f"  DrugBank: {d.get('drugbank', 'N/A')}")
print("PASS: Safety check OK")
PYEOF

# 5. Classifiers endpoint
echo ""
echo "=== TEST 5: Classifiers ==="
COUNT=$(curl -sf http://localhost:8000/api/classifiers | python3 -c "import json,sys; print(len(json.load(sys.stdin)['classifiers']))")
echo "  Classifiers available: $COUNT"
echo "PASS: Classifiers OK"

echo ""
echo "============================================"
echo " ALL TESTS PASSED"
echo "============================================"
