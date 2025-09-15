-- Check Reverb status values
SELECT DISTINCT vr_state, COUNT(*)
FROM vr_listings 
GROUP BY vr_state 
ORDER BY COUNT(*) DESC;