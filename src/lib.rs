use serde::{Deserialize, Serialize};
use sha2::Digest;
use std::path::{Path, PathBuf};
use chrono::{DateTime, Utc};

/// Errors in the data commons pipeline.
#[derive(Debug, thiserror::Error)]
pub enum CommonsError {
    #[error("Validation failed: {0}")]
    Validation(String),
    #[error("Quality too low: {score:.1}/100 (minimum: {minimum})")]
    QualityTooLow { score: f64, minimum: f64 },
    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),
    #[error("CSV error: {0}")]
    Csv(#[from] csv::Error),
    #[error("JSON error: {0}")]
    Json(#[from] serde_json::Error),
    #[error("Hash mismatch: expected {expected}, got {actual}")]
    HashMismatch { expected: String, actual: String },
}

pub type Result<T> = std::result::Result<T, CommonsError>;

/// A contribution to the data commons.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Contribution {
    /// Unique ID (SHA-256 hash of content).
    pub id: String,
    /// Contributor name.
    pub contributor: String,
    /// Submission timestamp.
    pub submitted_at: DateTime<Utc>,
    /// Substance being recorded.
    pub substance: String,
    /// Device ID.
    pub device_id: String,
    /// Number of sensor channels.
    pub n_channels: usize,
    /// Number of samples.
    pub n_samples: usize,
    /// Sensor models used.
    pub sensor_models: Vec<String>,
    /// Quality score (0-100).
    pub quality_score: f64,
    /// Verification status.
    pub status: ContributionStatus,
    /// Verification log.
    pub verification_log: Vec<String>,
    /// Path to the data file.
    pub data_path: PathBuf,
    /// Path to the metadata file.
    pub metadata_path: PathBuf,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum ContributionStatus {
    /// Just submitted, awaiting verification.
    Pending,
    /// Automated checks passed.
    AutoVerified,
    /// Human reviewed and approved.
    Approved,
    /// Rejected (with reason).
    Rejected(String),
    /// Published to the commons.
    Published,
}

/// Metadata for a contribution.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Metadata {
    pub substance: String,
    pub device_id: String,
    pub session_date: String,
    #[serde(default)]
    pub contributor: String,
    #[serde(default)]
    pub sensor_info: std::collections::HashMap<String, String>,
    #[serde(default)]
    pub sensor_units: std::collections::HashMap<String, String>,
    #[serde(default)]
    pub sensor_models: std::collections::HashMap<String, String>,
    #[serde(default)]
    pub notes: String,
    #[serde(default)]
    pub temperature_celsius: Option<f64>,
    #[serde(default)]
    pub humidity_percent: Option<f64>,
}

/// Quality scorer for contributions.
pub struct QualityScorer {
    /// Minimum quality score for acceptance.
    pub minimum_score: f64,
}

impl Default for QualityScorer {
    fn default() -> Self {
        Self { minimum_score: 60.0 }
    }
}

impl QualityScorer {
    /// Score a contribution from 0-100.
    pub fn score(&self, csv_path: &Path, metadata: &Metadata) -> Result<(f64, Vec<String>)> {
        let mut score = 0.0;
        let mut reasons = Vec::new();

        // 1. Signal quality (30 points)
        let signal_score = self.score_signal_quality(csv_path)?;
        score += signal_score * 30.0;
        reasons.push(format!("Signal quality: {:.1}/30", signal_score * 30.0));

        // 2. Baseline stability (25 points)
        let stability_score = self.score_baseline_stability(csv_path)?;
        score += stability_score * 25.0;
        reasons.push(format!("Baseline stability: {:.1}/25", stability_score * 25.0));

        // 3. Metadata completeness (20 points)
        let metadata_score = self.score_metadata_completeness(metadata);
        score += metadata_score * 20.0;
        reasons.push(format!("Metadata completeness: {:.1}/20", metadata_score * 20.0));

        // 4. Session duration (15 points)
        let duration_score = self.score_duration(csv_path)?;
        score += duration_score * 15.0;
        reasons.push(format!("Session duration: {:.1}/15", duration_score * 15.0));

        // 5. Novelty (10 points) - placeholder, needs commons lookup
        score += 5.0; // Default middle score
        reasons.push("Novelty: 5.0/10 (default, needs commons lookup)".to_string());

        Ok((score, reasons))
    }

    fn score_signal_quality(&self, csv_path: &Path) -> Result<f64> {
        let mut rdr = csv::Reader::from_path(csv_path)?;
        let headers: Vec<String> = rdr.headers()?.iter().map(|s| s.to_string()).collect();

        let sensor_cols: Vec<usize> = headers.iter().enumerate()
            .filter(|(_, h)| h.starts_with("sensor_") || h.starts_with("MQ") || h.starts_with("ch"))
            .map(|(i, _)| i)
            .collect();

        if sensor_cols.is_empty() {
            return Ok(0.0);
        }

        let mut all_values: Vec<Vec<f64>> = Vec::new();
        for result in rdr.records() {
            let record = result?;
            let row: Vec<f64> = sensor_cols.iter()
                .filter_map(|&i| record.get(i).and_then(|s| s.parse().ok()))
                .collect();
            if !row.is_empty() {
                all_values.push(row);
            }
        }

        if all_values.len() < 10 {
            return Ok(0.0);
        }

        // SNR: signal power / noise power
        let n_channels = all_values[0].len();
        let mut total_snr = 0.0;
        for ch in 0..n_channels {
            let vals: Vec<f64> = all_values.iter().map(|r| r[ch]).collect();
            let mean = vals.iter().sum::<f64>() / vals.len() as f64;
            let signal_power = mean * mean;
            let noise_power = vals.iter().map(|v| (v - mean).powi(2)).sum::<f64>() / vals.len() as f64;
            let snr = if noise_power > 0.0 { signal_power / noise_power } else { 100.0 };
            total_snr += (snr / 100.0).min(1.0); // Normalize to 0-1
        }
        Ok(total_snr / n_channels as f64)
    }

    fn score_baseline_stability(&self, csv_path: &Path) -> Result<f64> {
        let mut rdr = csv::Reader::from_path(csv_path)?;
        let headers: Vec<String> = rdr.headers()?.iter().map(|s| s.to_string()).collect();

        let sensor_cols: Vec<usize> = headers.iter().enumerate()
            .filter(|(_, h)| h.starts_with("sensor_") || h.starts_with("MQ") || h.starts_with("ch"))
            .map(|(i, _)| i)
            .collect();

        let mut all_values: Vec<Vec<f64>> = Vec::new();
        for result in rdr.records() {
            let record = result?;
            let row: Vec<f64> = sensor_cols.iter()
                .filter_map(|&i| record.get(i).and_then(|s| s.parse().ok()))
                .collect();
            if !row.is_empty() {
                all_values.push(row);
            }
        }

        if all_values.len() < 20 {
            return Ok(0.0);
        }

        // Compare first 20% to last 20% baseline stability
        let n = all_values.len();
        let first_end = n / 5;
        let last_start = n - n / 5;

        let n_channels = all_values[0].len();
        let mut stability = 0.0;
        for ch in 0..n_channels {
            let first_mean: f64 = all_values[..first_end].iter().map(|r| r[ch]).sum::<f64>() / first_end as f64;
            let last_mean: f64 = all_values[last_start..].iter().map(|r| r[ch]).sum::<f64>() / (n - last_start) as f64;
            let drift = if first_mean.abs() > 1e-10 {
                (last_mean - first_mean).abs() / first_mean.abs()
            } else { 0.0 };
            stability += (1.0 - drift).max(0.0);
        }
        Ok(stability / n_channels as f64)
    }

    fn score_metadata_completeness(&self, metadata: &Metadata) -> f64 {
        let mut score = 0.0;
        if !metadata.substance.is_empty() { score += 0.25; }
        if !metadata.device_id.is_empty() { score += 0.25; }
        if !metadata.session_date.is_empty() { score += 0.25; }
        if !metadata.sensor_info.is_empty() { score += 0.15; }
        if !metadata.notes.is_empty() { score += 0.10; }
        score
    }

    fn score_duration(&self, csv_path: &Path) -> Result<f64> {
        let mut rdr = csv::Reader::from_path(csv_path)?;
        let mut count = 0;
        for _ in rdr.records() {
            count += 1;
        }
        // Optimal: 100-1000 samples (10-100 seconds at 10Hz)
        if count >= 100 && count <= 1000 {
            Ok(1.0)
        } else if count >= 50 {
            Ok(0.7)
        } else if count >= 10 {
            Ok(0.3)
        } else {
            Ok(0.0)
        }
    }
}

/// Verification pipeline.
pub struct VerificationPipeline {
    scorer: QualityScorer,
    approved_dir: PathBuf,
    pending_dir: PathBuf,
}

impl VerificationPipeline {
    pub fn new(data_dir: &Path) -> Self {
        let approved = data_dir.join("approved");
        let pending = data_dir.join("pending");
        std::fs::create_dir_all(&approved).ok();
        std::fs::create_dir_all(&pending).ok();

        Self {
            scorer: QualityScorer::default(),
            approved_dir: approved,
            pending_dir: pending,
        }
    }

    /// Submit a contribution for verification.
    pub fn submit(&self, csv_path: &Path, metadata_path: &Path) -> Result<Contribution> {
        // Load metadata
        let metadata_str = std::fs::read_to_string(metadata_path)?;
        let metadata: Metadata = serde_json::from_str(&metadata_str)?;

        // Compute quality score
        let (quality_score, mut verification_log) = self.scorer.score(csv_path, &metadata)?;

        // Compute content hash
        let content = std::fs::read(csv_path)?;
        let hash = format!("{:x}", sha2::Sha256::digest(&content));

        // Count samples and channels
        let mut rdr = csv::Reader::from_path(csv_path)?;
        let headers: Vec<String> = rdr.headers()?.iter().map(|s| s.to_string()).collect();
        let sensor_cols: Vec<usize> = headers.iter().enumerate()
            .filter(|(_, h)| h.starts_with("sensor_") || h.starts_with("MQ") || h.starts_with("ch"))
            .map(|(i, _)| i)
            .collect();
        let n_channels = sensor_cols.len();

        let mut n_samples = 0;
        for result in rdr.records() {
            if result.is_ok() {
                n_samples += 1;
            }
        }

        // Determine status
        let status = if quality_score >= self.scorer.minimum_score {
            verification_log.push(format!("PASSED: Quality score {:.1} >= {:.1}", quality_score, self.scorer.minimum_score));
            ContributionStatus::AutoVerified
        } else {
            verification_log.push(format!("REJECTED: Quality score {:.1} < {:.1}", quality_score, self.scorer.minimum_score));
            ContributionStatus::Rejected(format!("Quality score {:.1} below minimum {:.1}", quality_score, self.scorer.minimum_score))
        };

        let contribution = Contribution {
            id: hash,
            contributor: metadata.contributor.clone(),
            submitted_at: Utc::now(),
            substance: metadata.substance.clone(),
            device_id: metadata.device_id.clone(),
            n_channels,
            n_samples,
            sensor_models: metadata.sensor_models.values().cloned().collect(),
            quality_score,
            status,
            verification_log,
            data_path: csv_path.to_path_buf(),
            metadata_path: metadata_path.to_path_buf(),
        };

        // Save to pending directory
        let contribution_path = self.pending_dir.join(format!("{}.json", contribution.id));
        let contribution_json = serde_json::to_string_pretty(&contribution)?;
        std::fs::write(&contribution_path, contribution_json)?;

        Ok(contribution)
    }

    /// Approve a pending contribution (human review).
    pub fn approve(&self, contribution_id: &str) -> Result<Contribution> {
        let pending_path = self.pending_dir.join(format!("{}.json", contribution_id));
        let contribution_str = std::fs::read_to_string(&pending_path)?;
        let mut contribution: Contribution = serde_json::from_str(&contribution_str)?;

        contribution.status = ContributionStatus::Approved;
        contribution.verification_log.push(format!("Approved by human reviewer at {}", Utc::now()));

        // Move to approved directory
        let approved_path = self.approved_dir.join(format!("{}.json", contribution_id));
        let contribution_json = serde_json::to_string_pretty(&contribution)?;
        std::fs::write(&approved_path, contribution_json)?;
        std::fs::remove_file(&pending_path)?;

        Ok(contribution)
    }

    /// List all pending contributions.
    pub fn list_pending(&self) -> Result<Vec<Contribution>> {
        let mut contributions = Vec::new();
        if self.pending_dir.exists() {
            for entry in std::fs::read_dir(&self.pending_dir)? {
                let entry = entry?;
                if entry.path().extension().map_or(false, |e| e == "json") {
                    let content = std::fs::read_to_string(entry.path())?;
                    let contribution: Contribution = serde_json::from_str(&content)?;
                    contributions.push(contribution);
                }
            }
        }
        Ok(contributions)
    }

    /// List all approved contributions.
    pub fn list_approved(&self) -> Result<Vec<Contribution>> {
        let mut contributions = Vec::new();
        if self.approved_dir.exists() {
            for entry in std::fs::read_dir(&self.approved_dir)? {
                let entry = entry?;
                if entry.path().extension().map_or(false, |e| e == "json") {
                    let content = std::fs::read_to_string(entry.path())?;
                    let contribution: Contribution = serde_json::from_str(&content)?;
                    contributions.push(contribution);
                }
            }
        }
        Ok(contributions)
    }

    /// Load a single contribution from either the pending or approved store.
    pub fn get(&self, contribution_id: &str) -> Result<Contribution> {
        for dir in [&self.pending_dir, &self.approved_dir] {
            let path = dir.join(format!("{}.json", contribution_id));
            if path.exists() {
                let content = std::fs::read_to_string(&path)?;
                return Ok(serde_json::from_str(&content)?);
            }
        }
        Err(CommonsError::Validation(format!(
            "Contribution {} not found",
            contribution_id
        )))
    }

    /// All contributions across both stores (full Data Hub lifecycle).
    pub fn list_all(&self) -> Result<Vec<Contribution>> {
        let mut contributions = Vec::new();
        contributions.extend(self.list_pending()?);
        contributions.extend(self.list_approved()?);
        Ok(contributions)
    }

    fn write_contribution(&self, contribution: &Contribution) -> Result<()> {
        let json = serde_json::to_string_pretty(contribution)?;
        let approved = matches!(contribution.status, ContributionStatus::Approved | ContributionStatus::Published);
        let dir = if approved { &self.approved_dir } else { &self.pending_dir };
        let path = dir.join(format!("{}.json", contribution.id));
        std::fs::write(&path, json)?;
        // Ensure it is not also parked in the other store.
        let other = if approved { &self.pending_dir } else { &self.approved_dir };
        let _ = std::fs::remove_file(other.join(format!("{}.json", contribution.id)));
        Ok(())
    }

    /// Reject a pending contribution with a human-provided reason.
    pub fn reject(&self, contribution_id: &str, reason: &str) -> Result<Contribution> {
        let mut contribution = self.get(contribution_id)?;
        if !matches!(contribution.status, ContributionStatus::Pending | ContributionStatus::AutoVerified) {
            return Err(CommonsError::Validation(format!(
                "Contribution {} is not reviewable (status {:?})",
                contribution_id, contribution.status
            )));
        }
        contribution.status = ContributionStatus::Rejected(reason.to_string());
        contribution
            .verification_log
            .push(format!("Rejected by human reviewer: {}", reason));
        self.write_contribution(&contribution)?;
        Ok(contribution)
    }

    /// Move an approved contribution to Published (the only state eligible for
    /// community upload).
    pub fn publish(&self, contribution_id: &str) -> Result<Contribution> {
        let mut contribution = self.get(contribution_id)?;
        let attributable = matches!(contribution.status, ContributionStatus::Approved);
        if !attributable {
            return Err(CommonsError::Validation(format!(
                "Only approved contributions can be published (status {:?})",
                contribution.status
            )));
        }
        contribution.status = ContributionStatus::Published;
        contribution
            .verification_log
            .push(format!("Published to data commons at {}", Utc::now()));
        self.write_contribution(&contribution)?;
        Ok(contribution)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::io::Write;

    fn create_test_csv(path: &Path) {
        let mut file = std::fs::File::create(path).unwrap();
        writeln!(file, "timestamp,sensor_1,sensor_2,sensor_3").unwrap();
        for i in 0..100 {
            writeln!(file, "{},100.0,200.0,300.0", i as f64 * 0.1).unwrap();
        }
    }

    fn create_test_metadata(path: &Path) {
        let metadata = Metadata {
            substance: "coffee".to_string(),
            device_id: "esp32-mq3".to_string(),
            session_date: "2026-08-20".to_string(),
            contributor: "test".to_string(),
            sensor_info: std::collections::HashMap::new(),
            sensor_units: std::collections::HashMap::new(),
            sensor_models: std::collections::HashMap::new(),
            notes: "Test recording".to_string(),
            temperature_celsius: Some(22.0),
            humidity_percent: Some(55.0),
        };
        let json = serde_json::to_string_pretty(&metadata).unwrap();
        std::fs::write(path, json).unwrap();
    }

    #[test]
    fn test_quality_scoring() {
        let tmp = std::env::temp_dir().join("opensmell_test");
        std::fs::create_dir_all(&tmp).unwrap();

        let csv_path = tmp.join("test.csv");
        let meta_path = tmp.join("test.json");
        create_test_csv(&csv_path);
        create_test_metadata(&meta_path);

        let scorer = QualityScorer::default();
        let metadata_str = std::fs::read_to_string(&meta_path).unwrap();
        let metadata: Metadata = serde_json::from_str(&metadata_str).unwrap();
        let (score, reasons) = scorer.score(&csv_path, &metadata).unwrap();

        assert!(score > 50.0, "Score {} should be > 50", score);
        println!("Quality score: {:.1}", score);
        for reason in &reasons {
            println!("  {}", reason);
        }

        std::fs::remove_dir_all(&tmp).ok();
    }

    #[test]
    fn test_verification_pipeline() {
        let tmp = std::env::temp_dir().join("opensmell_pipeline_test");
        std::fs::create_dir_all(&tmp).unwrap();

        let csv_path = tmp.join("test.csv");
        let meta_path = tmp.join("test.json");
        create_test_csv(&csv_path);
        create_test_metadata(&meta_path);

        let pipeline = VerificationPipeline::new(&tmp);
        let contribution = pipeline.submit(&csv_path, &meta_path).unwrap();

        assert!(!contribution.id.is_empty());
        assert!(contribution.quality_score > 50.0);

        // List pending
        let pending = pipeline.list_pending().unwrap();
        assert_eq!(pending.len(), 1);

        // Approve
        let approved = pipeline.approve(&contribution.id).unwrap();
        assert_eq!(approved.status, ContributionStatus::Approved);

        // Verify moved to approved
        let approved_list = pipeline.list_approved().unwrap();
        assert_eq!(approved_list.len(), 1);

        let pending_after = pipeline.list_pending().unwrap();
        assert_eq!(pending_after.len(), 0);

        std::fs::remove_dir_all(&tmp).ok();
    }

    #[test]
    fn test_publish_lifecycle() {
        let tmp = std::env::temp_dir().join("opensmell_publish_test");
        std::fs::create_dir_all(&tmp).unwrap();

        let csv_path = tmp.join("test.csv");
        let meta_path = tmp.join("test.json");
        create_test_csv(&csv_path);
        create_test_metadata(&meta_path);

        let pipeline = VerificationPipeline::new(&tmp);
        let contribution = pipeline.submit(&csv_path, &meta_path).unwrap();
        let id = contribution.id.clone();

        // Cannot publish while only auto-verified/pending.
        assert!(pipeline.publish(&id).is_err());

        // Approve then publish.
        pipeline.approve(&id).unwrap();
        let published = pipeline.publish(&id).unwrap();
        assert_eq!(published.status, ContributionStatus::Published);
        assert!(pipeline.get(&id).unwrap().status == ContributionStatus::Published);

        // Reject on a published contribution is rejected.
        assert!(pipeline.reject(&id, "nope").is_err());

        // list_all surfaces everything.
        assert_eq!(pipeline.list_all().unwrap().len(), 1);

        std::fs::remove_dir_all(&tmp).ok();
    }
}
