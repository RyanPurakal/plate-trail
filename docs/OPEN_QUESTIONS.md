# Open questions

Things noted while finishing the project, for a decision or follow-up. None of them block the current results. Each item has a recommendation.

## Needs you

1. **Run the real-data validation on your own Timeline.** The importer is built and tested on synthetic exports, but it has not seen a real file. Steps: [real_data_validation.md](real_data_validation.md) (export from your phone, then `python -m platetrail.realdata.validate Timeline.json`). It only produces a number if you drove in Edison or New Brunswick during the period. *Recommendation:* run it once and add the output to the README's "Inference on real movement" table. If others contribute data, get their written consent first, and run the tool on their machine rather than collecting files.

## Modelling choices worth a second look

2. **The engine's work detection is weak on sparse cameras.** 56% of workers get no work estimate on the OSM network (F6), because the engine needs a weekday gap of 3–12 h bracketed by reads. The naive "camera before the longest gap" rule answers far more often. *Option:* fall back to that rule, flagged low confidence, when no long stay exists. Not done, because it would make the engine partly the baseline it is compared against. *Recommendation:* keep as is and report it as a limitation (as F6 does).

3. **Confidence measures consistency, not proximity.** A "high" home estimate is 3.6 km off at the median on the OSM network. The UI and F6 say so. *Option:* fold camera-to-cluster distance into confidence, or show the radius more prominently. *Recommendation:* leave the label honest and explained, as it is now.

4. **Multi-year retention is not simulated.** The proposal compares 7 days with 3 years. Simulations run up to 4 weeks, and retention beyond the period equals "no limits". Longer histories can only add evidence, so the 4-week numbers are a lower bound for long retention. *Option:* a 52-week run for about 100 drivers (hours of compute) to show the trend. *Recommendation:* state it as a lower bound (done in F7).

5. **Unicity crowd size.** Simulated crowds are 1,000 cars. Edison PD's portal reports 518,797 "unique plate reads" in 30 days, and it isn't clear whether that means distinct plates or reads. *Option:* a 10,000-driver population to extend the crowd-size curve (roughly 10× the population #2 runtime). *Recommendation:* report the shares as upper bounds (done in F5).

6. **Placement of the 92 approved cameras is assumed** (arterials, length-weighted, 300 m apart). Real locations would change F5–F7's density rows. *Recommendation:* if Edison publishes locations, load them as a camera source and rerun `scripts/sensitivity.py` and populations #3–#4.

7. **Which Edison network is right?** OSM maps 40 Flock cameras in Edison and the PD portal counts 24. The difference is probably private and other-agency cameras ([camera_sources.md](camera_sources.md)). All results use the OSM network as mapped.

8. **Misreads never collide with another real car's plate.** A misread lands on a random look-alike string. Real misreads sometimes hit another real plate, which harms a second person. That is probably an underestimate of harm, but it doesn't change the per-driver results.

## Done differently from the proposal

- **DeFlock** is not a separate loader: DeFlock stores its cameras in OpenStreetMap, so loading OSM loads DeFlock ([camera_sources.md](camera_sources.md)).
- **Agency portals give counts only** (no locations), so they are used for a count cross-check, not as a camera source.
- **"Consenting volunteers"** became a local, single-person importer. No volunteer data was collected (item 1 above).
