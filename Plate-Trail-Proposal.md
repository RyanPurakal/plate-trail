**Project Title:** Plate Trail: What License Plate Cameras Can Reconstruct About Your Week  
**Problem Being Addressed**  
Automated license plate reader (ALPR) networks led by Flock Safety are expanding fast; Edison, NJ recently approved 92 additional Flock cameras. The public debate is stuck: supporters say cameras only log a plate at a few fixed points, while critics say enough reads reveal a person's whole routine. Neither side usually backs its claim with real camera positions and measured numbers. This affects every driver in a covered area, plus the residents, council members, and journalists deciding on deployment and retention; New Jersey allows plate data to be kept for years. It matters because courts increasingly ask how complete a picture location data paints (the "mosaic" argument in *Carpenter v. United States*), and that question is usually answered by intuition.  
**Intended Solution**  
Plate Trail measures what a history of ALPR reads can reveal about a driver, using real camera locations in Edison and New Brunswick, realistic travel behavior, and a population-scale analysis of how quickly drivers become uniquely identifiable. It builds weekly routines from real trip diaries in the National Household Travel Survey (NHTS), routes each trip on the real road network, and determines which cameras capture the vehicle based on location and facing direction; a sensor model adds missed reads, character misreads, camera downtime, and timestamp jitter. From the read log alone, an inference engine infers likely home and work or school areas, the recurring weekly schedule, and anomalous trips, shown as plain-language conclusions with confidence levels. A population analysis of about 1,000 simulated drivers measures unicity, the share of drivers uniquely matched by p of their own reads (following *Unique in the Crowd*, de Montjoye et al., 2013), and a policy comparison ranks levers an agency could adopt (retention from 7 days to 3 years, rounding timestamps to the hour, aggregate-only results, limited search windows) by how much each reduces inference accuracy and unicity. A "your week" mode lets a user describe their typical week and see what could be inferred about them; inputs are session-only and never stored.  
**Existing Work and Differentiation**  
Camera maps (DeFlock, MyTownView) show where cameras are. FlockHopper counts cameras on a single route and suggests an avoidance route, storing no history. Plate Trail adds what these lack: a time dimension (multi-week histories), an inference layer, a population-level identifiability measurement, and a quantitative policy comparison.  
**Capstone Track:** Computer Science / ITI  
**Planned Technologies**

> * Frontend: Next.js (React), MapLibre  
> * Backend: FastAPI (Python)  
> * Database: PostgreSQL with PostGIS  
> * Geospatial: OSMnx, NetworkX, Overpass API  
> * Machine learning: scikit-learn (HDBSCAN), statistical schedule modeling, anomaly detection  
> * Jobs and cache: Redis, Celery  
> * Tooling: Git/GitHub, Docker, pytest with GitHub Actions

**Required Components**

> * **Frontend:** interactive map, read log table, step-by-step reveal, unicity charts, policy controls, "your week" flow  
> * **Backend:** API for simulation, inference, unicity, and policy runs  
> * **Database:** PostGIS store of cameras, road network, simulation runs, read logs, and results

**Planned Additional Technical Components**

> 1. **Direction-aware camera matching (algorithm):** routing plus direction-aware matching of trips to cameras, with a tunable sensor noise model.  
> 2. **Multi-source camera ETL (data pipeline / ETL):** merges camera data from OpenStreetMap, DeFlock, and agency transparency portals; deduplicates, cross-checks, and snaps cameras to road segments; processes NHTS trip diaries.  
> 3. **Spatiotemporal inference engine (machine learning):** clustering for anchor locations, schedule reconstruction, and anomaly detection.  
> 4. **Population simulation queue (background jobs):** population-scale simulation and unicity runs execute on a Celery queue with progress reporting.  
> 5. **Graph and coverage cache (caching):** Redis caches the road graph, coverage lookups, and repeated runs to keep controls responsive.

**Technical Design**  
Camera sources and NHTS feed an ETL pipeline into PostGIS. The frontend calls FastAPI, which sends jobs to a Celery queue; a simulation worker handles routines, routing, camera matching, sensor noise, and read log generation, then an inference and unicity worker writes to the results store, with Redis between the API and heavy computation. The architecture diagram will be in the README and Checkpoint 2\.  
**Testing and Validation**

> * **Inference on synthetic drivers:** compare inferences with known ground truth; measure home/work distance error, percent of schedule recovered, and anomaly precision and recall.  
> * **Inference on real movement:** run on real location history exports (own, plus volunteers); same metrics against each person's confirmed places.  
> * **Robustness to assumptions:** sensitivity sweeps over noise, density, and direction assumptions; accuracy and unicity under each setting, with best and worst case for unknown directions.  
> * **Camera data accuracy:** cross-check sources against each other and public records; report agreement rate and document discrepancies.  
> * **Software:** pytest unit and API integration tests in CI; all tests pass on every push.

**Timeline**

> * **Week 1:** multi-source camera ETL, PostGIS schema, NHTS processing (Checkpoint 1\)  
> * **Week 2:** road network, routing, camera matching, sensor noise model, architecture diagram (Checkpoint 2\)  
> * **Week 3:** routine generator, read logs, task queue  
> * **Week 4:** inference engine and basic map frontend (Checkpoint 3\)  
> * **Week 5:** population unicity analysis, policy comparison, reveal UI, caching  
> * **Week 6:** real-data validation, "your week" mode, documentation, presentation (Checkpoint 4\)

**Risks, Limitations, and Ethics**

> * **Sparse camera data:** about 42 cameras are publicly documented in Edison; if density is too low, expand to Middlesex County and model the newly approved cameras as a density setting.  
> * **Missing direction tags:** report best and worst case.  
> * **NHTS is national, not local:** it supplies realistic trip patterns while destinations come from real Edison and New Brunswick places.  
> * **Scope:** start with 1,000 drivers; "your week" mode is last.  
> * **Ethics:** no real plate reads are used; real location data comes only from consenting individuals, is processed locally, and is never stored; only public camera data is used; the project measures what the data can and cannot reveal rather than advocating a side.  
> * **Future work:** more towns, mobile ALPR (patrol cars), and publishing results for local council use.

