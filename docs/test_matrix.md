# Matricea testelor O1–O6

Matricea leagă cerințele de implementare de testele automate. Testele de grafice
și randare folosesc fixture-uri sintetice în memorie și rularea temporară
`fixture_render`, creată în `tests/test_render.py`; ele nu citesc direct artefactele
din `results/runs/pilot_01`.

| Obiectiv | Cerință | Implementare | Dovezi prin teste |
|---|---|---|---|
| O1 / A1 | Normalizarea câmpurilor TLC la `pickup_at`, `distance_miles`, `pickup_zone`; păstrarea perioadei și a populației eligibile comune. | `src/data.py:register_trips`; `src/sql/register_trips.sql` | `tests/test_sampling_cli.py:SamplingCliTests.test_cli_uses_src_data_register_trips_and_verifies_parquet_schema_and_rows`; `tests/test_data.py:TestDataModuleIntegration.test_query_integration`; `tests/test_queries.py:QueryTests.test_hourly_and_distance_queries_share_eligible_population` |
| O2 | Numărători brute prin `query_counts`; allow-list pentru surse; 24 de ore și 5 intervale cu limite explicite. | `src/queries.py:query_counts`; `src/sql/hours.sql`; `src/sql/distance.sql` | `tests/test_queries.py:QueryTests.test_query_counts_hours_for_both_sources`, `test_query_counts_distance_for_both_sources`, `test_invalid_source_fails_before_sql`, `test_empty_views_return_all_categories`, `test_distance_boundaries_are_explicit`; `tests/test_data.py:TestDataModuleIntegration.test_query_integration` |
| O3 | Aplicarea o singură dată a ponderii `count/p`, în afara SQL; validarea probabilității și seed-ului; eșantion reproductibil și metadata în artefacte. | `src/sampling_core/estimation.py:estimate_counts`; `src/sampling_core/engine.py:sample_and_query` | `tests/test_sampling_estimation.py:SamplingEstimationTests.test_pairs_dict_and_dataframe_preserve_keys_and_scale_once`, `test_invalid_probabilities_rejected`; `tests/test_sampling_engine.py:SamplingEngineTests.test_end_to_end_query_estimator_and_evaluate_with_non_unit_probability`, `test_same_inputs_and_seed_reproduce_multiset`; `tests/test_benchmark.py:BenchmarkIntegrationTests.test_real_modules_produce_complete_matrix_and_correct_estimates` |
| O4 | Validarea intrărilor metricilor, merge exterior, păstrarea statusurilor și tratarea totalurilor zero. | `src/metrics.py:evaluate`, `calculate_hours_error`, `calculate_distance_total_variation`; `src/benchmark.py:run_benchmark` | `tests/test_edge_cases.py:MetricEdgeCaseTests.test_nan_negative_duplicate_and_missing_column_inputs_rejected`, `test_null_keys_and_incompatible_key_formats_rejected`, `test_missing_categories_are_zero_filled_by_outer_merge`, `test_tvd_zero_total_statuses`, `test_hour_zero_total_statuses`, `test_category_order_invariance`; `tests/test_benchmark.py:BenchmarkIntegrationTests.test_real_modules_produce_complete_matrix_and_correct_estimates` |
| O5 | Proporții normalizate independent pentru ore și distanțe; selector 1%/10%, seed 42; afișarea erorilor calculate față de numărătorile exacte din pilot; export HTML autonom. | `src/figures_hours.py:build_hours_figure`; `src/plots.py:plot_distance_distribution`; `src/render.py:build_pilot_figures`, `render_pilot`; `src/demo.py:main` | `tests/test_figures_hours.py:HoursFigureTests.test_ordered_hours_and_selector_keep_exact_visible`, `test_metric_error_is_displayed_and_updates_with_selector`; `tests/test_plot.py:PlotTests.test_normalized_data_labels_order_and_metadata`, `test_sample_percentage_selector_keeps_axis_scale`, `test_empty_sample_label_follows_selected_rate`; `tests/test_render.py:RenderIntegrationTests.test_render_cli_exports_two_self_contained_figures` |
| O6 | Acoperirea intrărilor invalide/goale, excluderilor, totalurilor zero, populației comune, graficelor și exportului offline; matrice reproductibilă și ușor de găsit. | `tests/`; `docs/reproduce.md`; `src/render.py` | Comanda completă: `python -m unittest discover -s tests -p "test_*.py" -v`; teste relevante: `tests/test_data.py:TestExclusionsReconciliation.test_fixture_exclusions_exact_reconciliation`, `tests/test_sampling_artifacts.py:SamplingArtifactsTests.test_empty_source_produces_valid_empty_sample_and_manifest`, `tests/test_render.py:RenderIntegrationTests.test_render_cli_exports_two_self_contained_figures` |

## Verificări pentru referința pilot

Rândurile reale de metrici pentru `pilot_01` din `errors.csv` sunt recalculate
din rândurile exacte și estimate din `results.csv` înainte ca rendererul să le
afișeze. Rendererul respinge rândurile lipsă, duplicate, învechite sau
inconsistente. Graficele 1% și 10% sunt selectate din manifestul rulării și
preiau seed-ul 42 și perioada analizei.
