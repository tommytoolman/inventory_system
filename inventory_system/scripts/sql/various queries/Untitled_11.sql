-- SELECT 
--     reverb_state,
--     COUNT(*) as count
-- FROM reverb_listings
-- GROUP BY reverb_state
-- ORDER BY count DESC;

-- SELECT column_name 
-- FROM information_schema.columns 
-- WHERE table_name = 'reverb_listings' 
-- ORDER BY ordinal_position;

            SELECT reverb_state, COUNT(*) as count 
            FROM reverb_listings 
            GROUP BY reverb_state
            ORDER BY reverb_state