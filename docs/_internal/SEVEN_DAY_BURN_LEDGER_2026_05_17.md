
## tick 2026-05-17T03:19:52.197363+00:00

```json
{
  "ts": "2026-05-17T03:19:52.197363+00:00",
  "ramp_start": "2026-05-17",
  "ramp_days": 7,
  "mtd_gross_usd": 3101.7995734788,
  "mtd_net_usd": 2.086e-07,
  "credit_remaining_usd": 16388.2004265212,
  "hard_stop_usd": 18300.0,
  "never_reach_usd": 19490.0,
  "daily_target_lo_usd": 1800.0,
  "daily_target_hi_usd": 2800.0,
  "planned_daily_burn_usd": 2965.0,
  "planned_7d_burn_usd": 20755.0,
  "sub_plans": [
    {
      "step": "scale_gpu_compute_env",
      "compute_env": "jpcite-credit-ec2-spot-gpu",
      "before_max_vcpus": 64,
      "after_max_vcpus": 256,
      "burn_per_day_usd": 1000.0,
      "burn_7d_usd": 7000.0,
      "instance_types": [
        "g4dn.4xlarge",
        "g4dn.8xlarge",
        "g4dn.12xlarge",
        "g5.4xlarge",
        "g5.8xlarge",
        "g5.12xlarge"
      ],
      "target_concurrent_jobs": 5,
      "dry_run": true
    },
    {
      "step": "plan_sagemaker_train_cycle",
      "cron_rate": "rate(6 hours)",
      "training_cycles": [
        {
          "tag": "M5_v2_simcse_iter",
          "submit_script": "sagemaker_simcse_finetune_2026_05_17.py",
          "instance": "ml.g4dn.12xlarge",
          "max_runtime_hours": 12,
          "cost_per_cycle_usd": 70.0,
          "cycles_per_7d": 28
        },
        {
          "tag": "M6_cross_encoder_iter",
          "submit_script": "sagemaker_cross_encoder_finetune_2026_05_17.py",
          "instance": "ml.g4dn.12xlarge",
          "max_runtime_hours": 12,
          "cost_per_cycle_usd": 70.0,
          "cycles_per_7d": 28
        },
        {
          "tag": "M11_active_learning_iter",
          "submit_script": "sagemaker_m11_al_iter_2026_05_17.py",
          "instance": "ml.g4dn.4xlarge",
          "max_runtime_hours": 6,
          "cost_per_cycle_usd": 30.0,
          "cycles_per_7d": 28
        },
        {
          "tag": "M11_distill_v2",
          "submit_script": "sagemaker_m11_distill_2026_05_17.py",
          "instance": "ml.g4dn.12xlarge",
          "max_runtime_hours": 12,
          "cost_per_cycle_usd": 60.0,
          "cycles_per_7d": 14
        },
        {
          "tag": "M11_kg_completion_iter",
          "submit_script": "sagemaker_kg_completion_submit_2026_05_17.py",
          "instance": "ml.g4dn.4xlarge",
          "max_runtime_hours": 6,
          "cost_per_cycle_usd": 25.0,
          "cycles_per_7d": 14
        },
        {
          "tag": "M11_multitask_v2_finetune",
          "submit_script": "sagemaker_multitask_finetune_2026_05_17.py",
          "instance": "ml.g4dn.12xlarge",
          "max_runtime_hours": 24,
          "cost_per_cycle_usd": 95.0,
          "cycles_per_7d": 7
        }
      ],
      "total_cycles_7d": 119,
      "burn_7d_usd": 6615.0,
      "dry_run": true
    },
    {
      "step": "plan_opensearch_sustained",
      "domain": "jpcite-xfact-2026-05",
      "instance_type": "r5.4xlarge.search",
      "instance_count": 3,
      "warm_type": "ultrawarm1.medium.search",
      "warm_count": 3,
      "master_type": "r5.large.search",
      "master_count": 3,
      "burn_per_day_usd": 130.0,
      "burn_7d_usd": 910.0,
      "note": "already LIVE; sustained 7-day is automatic."
    },
    {
      "step": "plan_athena_moat_queries",
      "cron_rate": "rate(30 minutes)",
      "queries": [
        "industry_x_geo_cohort_aggregation",
        "program_x_law_lineage_traverse",
        "case_cohort_match_at_scale",
        "amendment_diff_temporal_join",
        "ma_target_pool_full_corpus"
      ],
      "queries_per_day": 240,
      "avg_gb_scanned_per_query": 3.5,
      "burn_per_day_usd": 80.0,
      "burn_7d_usd": 560.0,
      "moat_note": "cross-source cohort + lineage traversal; outputs land in S3."
    },
    {
      "step": "plan_textract_continuous",
      "cron_rate": "rate(4 hours)",
      "pdfs_per_cycle": 200,
      "cycles_per_7d": 42,
      "pages_per_pdf_avg": 30,
      "burn_per_cycle_usd": 300.0,
      "burn_7d_usd": 2100.0,
      "moat_note": "ministry PDF OCR -> derived corpus -> embedding pipeline."
    },
    {
      "step": "plan_batch_transform_pm12",
      "cron_rate": "rate(24 hours)",
      "jobs_per_cycle": 20,
      "cost_per_cycle_usd": 250.0,
      "cycles_per_7d": 7,
      "burn_7d_usd": 1750.0,
      "moat_note": "embedding refresh: M5/M6 v2 -> FAISS shard re-index."
    },
    {
      "step": "plan_storage_burn",
      "s3_put_per_day_usd": 80.0,
      "glue_etl_per_day_usd": 100.0,
      "ebs_per_day_usd": 80.0,
      "burn_per_day_usd": 260.0,
      "burn_7d_usd": 1820.0,
      "moat_note": "embeddings + Textract output + Parquet shards."
    }
  ],
  "dry_run": true,
  "note": "EVERY DOLLAR MUST CONTRIBUTE TO MOAT."
}
```

## tick 2026-05-17T03:20:11.501886+00:00

```json
{
  "ts": "2026-05-17T03:20:11.501886+00:00",
  "ramp_start": "2026-05-17",
  "ramp_days": 7,
  "mtd_gross_usd": 3101.7995734788,
  "mtd_net_usd": 2.086e-07,
  "credit_remaining_usd": 16388.2004265212,
  "hard_stop_usd": 18300.0,
  "never_reach_usd": 19490.0,
  "daily_target_lo_usd": 1800.0,
  "daily_target_hi_usd": 2800.0,
  "planned_daily_burn_usd": 2265.0,
  "planned_7d_burn_usd": 15855.0,
  "sub_plans": [
    {
      "step": "scale_gpu_compute_env",
      "compute_env": "jpcite-credit-ec2-spot-gpu",
      "before_max_vcpus": 64,
      "after_max_vcpus": 256,
      "burn_per_day_usd": 300.0,
      "burn_7d_usd": 2100.0,
      "instance_types": [
        "g4dn.4xlarge",
        "g4dn.8xlarge",
        "g4dn.12xlarge",
        "g5.4xlarge",
        "g5.8xlarge",
        "g5.12xlarge"
      ],
      "target_concurrent_jobs": 5,
      "dry_run": true
    },
    {
      "step": "plan_sagemaker_train_cycle",
      "cron_rate": "rate(6 hours)",
      "training_cycles": [
        {
          "tag": "M5_v2_simcse_iter",
          "submit_script": "sagemaker_simcse_finetune_2026_05_17.py",
          "instance": "ml.g4dn.12xlarge",
          "max_runtime_hours": 12,
          "cost_per_cycle_usd": 70.0,
          "cycles_per_7d": 28
        },
        {
          "tag": "M6_cross_encoder_iter",
          "submit_script": "sagemaker_cross_encoder_finetune_2026_05_17.py",
          "instance": "ml.g4dn.12xlarge",
          "max_runtime_hours": 12,
          "cost_per_cycle_usd": 70.0,
          "cycles_per_7d": 28
        },
        {
          "tag": "M11_active_learning_iter",
          "submit_script": "sagemaker_m11_al_iter_2026_05_17.py",
          "instance": "ml.g4dn.4xlarge",
          "max_runtime_hours": 6,
          "cost_per_cycle_usd": 30.0,
          "cycles_per_7d": 28
        },
        {
          "tag": "M11_distill_v2",
          "submit_script": "sagemaker_m11_distill_2026_05_17.py",
          "instance": "ml.g4dn.12xlarge",
          "max_runtime_hours": 12,
          "cost_per_cycle_usd": 60.0,
          "cycles_per_7d": 14
        },
        {
          "tag": "M11_kg_completion_iter",
          "submit_script": "sagemaker_kg_completion_submit_2026_05_17.py",
          "instance": "ml.g4dn.4xlarge",
          "max_runtime_hours": 6,
          "cost_per_cycle_usd": 25.0,
          "cycles_per_7d": 14
        },
        {
          "tag": "M11_multitask_v2_finetune",
          "submit_script": "sagemaker_multitask_finetune_2026_05_17.py",
          "instance": "ml.g4dn.12xlarge",
          "max_runtime_hours": 24,
          "cost_per_cycle_usd": 95.0,
          "cycles_per_7d": 7
        }
      ],
      "total_cycles_7d": 119,
      "burn_7d_usd": 6615.0,
      "dry_run": true
    },
    {
      "step": "plan_opensearch_sustained",
      "domain": "jpcite-xfact-2026-05",
      "instance_type": "r5.4xlarge.search",
      "instance_count": 3,
      "warm_type": "ultrawarm1.medium.search",
      "warm_count": 3,
      "master_type": "r5.large.search",
      "master_count": 3,
      "burn_per_day_usd": 130.0,
      "burn_7d_usd": 910.0,
      "note": "already LIVE; sustained 7-day is automatic."
    },
    {
      "step": "plan_athena_moat_queries",
      "cron_rate": "rate(30 minutes)",
      "queries": [
        "industry_x_geo_cohort_aggregation",
        "program_x_law_lineage_traverse",
        "case_cohort_match_at_scale",
        "amendment_diff_temporal_join",
        "ma_target_pool_full_corpus"
      ],
      "queries_per_day": 240,
      "avg_gb_scanned_per_query": 3.5,
      "burn_per_day_usd": 80.0,
      "burn_7d_usd": 560.0,
      "moat_note": "cross-source cohort + lineage traversal; outputs land in S3."
    },
    {
      "step": "plan_textract_continuous",
      "cron_rate": "rate(4 hours)",
      "pdfs_per_cycle": 200,
      "cycles_per_7d": 42,
      "pages_per_pdf_avg": 30,
      "burn_per_cycle_usd": 300.0,
      "burn_7d_usd": 2100.0,
      "moat_note": "ministry PDF OCR -> derived corpus -> embedding pipeline."
    },
    {
      "step": "plan_batch_transform_pm12",
      "cron_rate": "rate(24 hours)",
      "jobs_per_cycle": 20,
      "cost_per_cycle_usd": 250.0,
      "cycles_per_7d": 7,
      "burn_7d_usd": 1750.0,
      "moat_note": "embedding refresh: M5/M6 v2 -> FAISS shard re-index."
    },
    {
      "step": "plan_storage_burn",
      "s3_put_per_day_usd": 80.0,
      "glue_etl_per_day_usd": 100.0,
      "ebs_per_day_usd": 80.0,
      "burn_per_day_usd": 260.0,
      "burn_7d_usd": 1820.0,
      "moat_note": "embeddings + Textract output + Parquet shards."
    }
  ],
  "dry_run": true,
  "note": "EVERY DOLLAR MUST CONTRIBUTE TO MOAT."
}
```

## tick 2026-05-17T03:20:29.951561+00:00

```json
{
  "ts": "2026-05-17T03:20:29.951561+00:00",
  "ramp_start": "2026-05-17",
  "ramp_days": 7,
  "mtd_gross_usd": 3101.7995734788,
  "mtd_net_usd": 2.086e-07,
  "credit_remaining_usd": 16388.2004265212,
  "hard_stop_usd": 18300.0,
  "never_reach_usd": 19490.0,
  "daily_target_lo_usd": 1800.0,
  "daily_target_hi_usd": 2800.0,
  "planned_daily_burn_usd": 2157.8571428571427,
  "planned_7d_burn_usd": 15105.0,
  "sub_plans": [
    {
      "step": "scale_gpu_compute_env",
      "compute_env": "jpcite-credit-ec2-spot-gpu",
      "before_max_vcpus": 64,
      "after_max_vcpus": 256,
      "burn_per_day_usd": 300.0,
      "burn_7d_usd": 2100.0,
      "instance_types": [
        "g4dn.4xlarge",
        "g4dn.8xlarge",
        "g4dn.12xlarge",
        "g5.4xlarge",
        "g5.8xlarge",
        "g5.12xlarge"
      ],
      "target_concurrent_jobs": 5,
      "dry_run": true
    },
    {
      "step": "plan_sagemaker_train_cycle",
      "cron_rate": "rate(6 hours)",
      "training_cycles": [
        {
          "tag": "M5_v2_simcse_iter",
          "submit_script": "sagemaker_simcse_finetune_2026_05_17.py",
          "instance": "ml.g4dn.12xlarge",
          "max_runtime_hours": 12,
          "cost_per_cycle_usd": 70.0,
          "cycles_per_7d": 28
        },
        {
          "tag": "M6_cross_encoder_iter",
          "submit_script": "sagemaker_cross_encoder_finetune_2026_05_17.py",
          "instance": "ml.g4dn.12xlarge",
          "max_runtime_hours": 12,
          "cost_per_cycle_usd": 70.0,
          "cycles_per_7d": 28
        },
        {
          "tag": "M11_active_learning_iter",
          "submit_script": "sagemaker_m11_al_iter_2026_05_17.py",
          "instance": "ml.g4dn.4xlarge",
          "max_runtime_hours": 6,
          "cost_per_cycle_usd": 30.0,
          "cycles_per_7d": 28
        },
        {
          "tag": "M11_distill_v2",
          "submit_script": "sagemaker_m11_distill_2026_05_17.py",
          "instance": "ml.g4dn.12xlarge",
          "max_runtime_hours": 12,
          "cost_per_cycle_usd": 60.0,
          "cycles_per_7d": 14
        },
        {
          "tag": "M11_kg_completion_iter",
          "submit_script": "sagemaker_kg_completion_submit_2026_05_17.py",
          "instance": "ml.g4dn.4xlarge",
          "max_runtime_hours": 6,
          "cost_per_cycle_usd": 25.0,
          "cycles_per_7d": 14
        },
        {
          "tag": "M11_multitask_v2_finetune",
          "submit_script": "sagemaker_multitask_finetune_2026_05_17.py",
          "instance": "ml.g4dn.12xlarge",
          "max_runtime_hours": 24,
          "cost_per_cycle_usd": 95.0,
          "cycles_per_7d": 5
        }
      ],
      "total_cycles_7d": 117,
      "burn_7d_usd": 6425.0,
      "dry_run": true
    },
    {
      "step": "plan_opensearch_sustained",
      "domain": "jpcite-xfact-2026-05",
      "instance_type": "r5.4xlarge.search",
      "instance_count": 3,
      "warm_type": "ultrawarm1.medium.search",
      "warm_count": 3,
      "master_type": "r5.large.search",
      "master_count": 3,
      "burn_per_day_usd": 130.0,
      "burn_7d_usd": 910.0,
      "note": "already LIVE; sustained 7-day is automatic."
    },
    {
      "step": "plan_athena_moat_queries",
      "cron_rate": "rate(30 minutes)",
      "queries": [
        "industry_x_geo_cohort_aggregation",
        "program_x_law_lineage_traverse",
        "case_cohort_match_at_scale",
        "amendment_diff_temporal_join",
        "ma_target_pool_full_corpus"
      ],
      "queries_per_day": 240,
      "avg_gb_scanned_per_query": 3.5,
      "burn_per_day_usd": 80.0,
      "burn_7d_usd": 560.0,
      "moat_note": "cross-source cohort + lineage traversal; outputs land in S3."
    },
    {
      "step": "plan_textract_continuous",
      "cron_rate": "rate(4 hours)",
      "pdfs_per_cycle": 200,
      "cycles_per_7d": 42,
      "pages_per_pdf_avg": 30,
      "burn_per_cycle_usd": 300.0,
      "burn_7d_usd": 2100.0,
      "moat_note": "ministry PDF OCR -> derived corpus -> embedding pipeline."
    },
    {
      "step": "plan_batch_transform_pm12",
      "cron_rate": "rate(24 hours)",
      "jobs_per_cycle": 20,
      "cost_per_cycle_usd": 250.0,
      "cycles_per_7d": 7,
      "burn_7d_usd": 1750.0,
      "moat_note": "embedding refresh: M5/M6 v2 -> FAISS shard re-index."
    },
    {
      "step": "plan_storage_burn",
      "s3_put_per_day_usd": 50.0,
      "glue_etl_per_day_usd": 80.0,
      "ebs_per_day_usd": 50.0,
      "burn_per_day_usd": 180.0,
      "burn_7d_usd": 1260.0,
      "moat_note": "embeddings + Textract output + Parquet shards."
    }
  ],
  "dry_run": true,
  "note": "EVERY DOLLAR MUST CONTRIBUTE TO MOAT."
}
```

## tick 2026-05-17T03:22:40.510645+00:00

```json
{
  "ts": "2026-05-17T03:22:40.510645+00:00",
  "ramp_start": "2026-05-17",
  "ramp_days": 7,
  "mtd_gross_usd": 3101.7995734788,
  "mtd_net_usd": 2.086e-07,
  "credit_remaining_usd": 16388.2004265212,
  "hard_stop_usd": 18300.0,
  "never_reach_usd": 19490.0,
  "daily_target_lo_usd": 1800.0,
  "daily_target_hi_usd": 2800.0,
  "planned_daily_burn_usd": 2072.1428571428573,
  "planned_7d_burn_usd": 14505.0,
  "sub_plans": [
    {
      "step": "scale_gpu_compute_env",
      "compute_env": "jpcite-credit-ec2-spot-gpu",
      "before_max_vcpus": 64,
      "after_max_vcpus": 256,
      "burn_per_day_usd": 300.0,
      "burn_7d_usd": 2100.0,
      "instance_types": [
        "g4dn.4xlarge",
        "g4dn.8xlarge",
        "g4dn.12xlarge",
        "g5.4xlarge",
        "g5.8xlarge",
        "g5.12xlarge"
      ],
      "target_concurrent_jobs": 5,
      "dry_run": true
    },
    {
      "step": "plan_sagemaker_train_cycle",
      "cron_rate": "rate(6 hours)",
      "training_cycles": [
        {
          "tag": "M5_v2_simcse_iter",
          "submit_script": "sagemaker_simcse_finetune_2026_05_17.py",
          "instance": "ml.g4dn.12xlarge",
          "max_runtime_hours": 12,
          "cost_per_cycle_usd": 70.0,
          "cycles_per_7d": 28
        },
        {
          "tag": "M6_cross_encoder_iter",
          "submit_script": "sagemaker_cross_encoder_finetune_2026_05_17.py",
          "instance": "ml.g4dn.12xlarge",
          "max_runtime_hours": 12,
          "cost_per_cycle_usd": 70.0,
          "cycles_per_7d": 28
        },
        {
          "tag": "M11_active_learning_iter",
          "submit_script": "sagemaker_m11_al_iter_2026_05_17.py",
          "instance": "ml.g4dn.4xlarge",
          "max_runtime_hours": 6,
          "cost_per_cycle_usd": 30.0,
          "cycles_per_7d": 28
        },
        {
          "tag": "M11_distill_v2",
          "submit_script": "sagemaker_m11_distill_2026_05_17.py",
          "instance": "ml.g4dn.12xlarge",
          "max_runtime_hours": 12,
          "cost_per_cycle_usd": 60.0,
          "cycles_per_7d": 14
        },
        {
          "tag": "M11_kg_completion_iter",
          "submit_script": "sagemaker_kg_completion_submit_2026_05_17.py",
          "instance": "ml.g4dn.4xlarge",
          "max_runtime_hours": 6,
          "cost_per_cycle_usd": 25.0,
          "cycles_per_7d": 14
        },
        {
          "tag": "M11_multitask_v2_finetune",
          "submit_script": "sagemaker_multitask_finetune_2026_05_17.py",
          "instance": "ml.g4dn.12xlarge",
          "max_runtime_hours": 24,
          "cost_per_cycle_usd": 95.0,
          "cycles_per_7d": 5
        }
      ],
      "total_cycles_7d": 117,
      "burn_7d_usd": 6425.0,
      "dry_run": true
    },
    {
      "step": "plan_opensearch_sustained",
      "domain": "jpcite-xfact-2026-05",
      "instance_type": "r5.4xlarge.search",
      "instance_count": 3,
      "warm_type": "ultrawarm1.medium.search",
      "warm_count": 3,
      "master_type": "r5.large.search",
      "master_count": 3,
      "burn_per_day_usd": 130.0,
      "burn_7d_usd": 910.0,
      "note": "already LIVE; sustained 7-day is automatic."
    },
    {
      "step": "plan_athena_moat_queries",
      "cron_rate": "rate(30 minutes)",
      "queries": [
        "industry_x_geo_cohort_aggregation",
        "program_x_law_lineage_traverse",
        "case_cohort_match_at_scale",
        "amendment_diff_temporal_join",
        "ma_target_pool_full_corpus"
      ],
      "queries_per_day": 240,
      "avg_gb_scanned_per_query": 3.5,
      "burn_per_day_usd": 80.0,
      "burn_7d_usd": 560.0,
      "moat_note": "cross-source cohort + lineage traversal; outputs land in S3."
    },
    {
      "step": "plan_textract_continuous",
      "cron_rate": "rate(4 hours)",
      "pdfs_per_cycle": 200,
      "cycles_per_7d": 5,
      "pages_per_pdf_avg": 30,
      "burn_per_cycle_usd": 300.0,
      "burn_7d_usd": 1500.0,
      "moat_note": "ministry PDF OCR -> derived corpus -> embedding pipeline."
    },
    {
      "step": "plan_batch_transform_pm12",
      "cron_rate": "rate(24 hours)",
      "jobs_per_cycle": 20,
      "cost_per_cycle_usd": 250.0,
      "cycles_per_7d": 7,
      "burn_7d_usd": 1750.0,
      "moat_note": "embedding refresh: M5/M6 v2 -> FAISS shard re-index."
    },
    {
      "step": "plan_storage_burn",
      "s3_put_per_day_usd": 50.0,
      "glue_etl_per_day_usd": 80.0,
      "ebs_per_day_usd": 50.0,
      "burn_per_day_usd": 180.0,
      "burn_7d_usd": 1260.0,
      "moat_note": "embeddings + Textract output + Parquet shards."
    }
  ],
  "dry_run": true,
  "note": "EVERY DOLLAR MUST CONTRIBUTE TO MOAT."
}
```
