-- Q1  Latest blood pressure for one patient
SELECT effective, systolic, diastolic
FROM bp_readings
WHERE patient_id = 'p1'
ORDER BY effective DESC
LIMIT 1;

-- Q2  Patients whose most recent systolic is 140 or above
WITH latest AS (
  SELECT *, row_number() OVER (PARTITION BY patient_id ORDER BY effective DESC) AS rn
  FROM bp_readings
)
SELECT patient_id, systolic, effective
FROM latest
WHERE rn = 1 AND systolic >= 140
ORDER BY patient_id;

-- Q3  HbA1c trend for one patient over the last twelve months
SELECT effective, value
FROM lab_results
WHERE patient_id = 'p1' AND loinc = '4548-4' AND effective >= '2025-11-12'
ORDER BY effective;

-- Q4  Patients on active metformin whose latest HbA1c is above 7.5
WITH latest_a1c AS (
  SELECT *, row_number() OVER (PARTITION BY patient_id ORDER BY effective DESC) AS rn
  FROM lab_results
  WHERE loinc = '4548-4'
)
SELECT a.patient_id, a.value AS hba1c, a.effective
FROM latest_a1c a
JOIN medication_requests m ON m.patient_id = a.patient_id
WHERE a.rn = 1 AND a.value > 7.5 AND m.status = 'active' AND m.medication_code = 'MED-0001'
ORDER BY a.patient_id;
