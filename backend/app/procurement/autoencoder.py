"""
AuditAI — PyTorch Autoencoder for learning normal expense claim patterns.

Architecture: Input(N) → 64 → ReLU → 32 → ReLU → 16 (latent) → 32 → ReLU → 64 → ReLU → N (sigmoid)

The autoencoder learns to reconstruct normal claim feature vectors. Its reconstructed
output is then fed into the Isolation Forest (see isolation_forest.py), so anomalies
are detected in "what the model thinks normal looks like" rather than in noisy raw input.
"""
import logging
from pathlib import Path
from typing import Tuple

import joblib
import numpy as np
import torch
import torch.nn as nn
from sklearn.preprocessing import StandardScaler
from torch.utils.data import DataLoader, TensorDataset

logger = logging.getLogger(__name__)


class ExpenseAutoencoder(nn.Module):
    """
    Symmetric autoencoder for expense claim feature reconstruction.

    Encoder: input_dim → 64 → 32 → latent_dim
    Decoder: latent_dim → 32 → 64 → input_dim
    """

    def __init__(self, input_dim: int, latent_dim: int = 16):
        super().__init__()
        self.encoder = nn.Sequential(
            nn.Linear(input_dim, 64),
            nn.ReLU(),
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Linear(32, latent_dim),
            nn.ReLU(),
        )
        self.decoder = nn.Sequential(
            nn.Linear(latent_dim, 32),
            nn.ReLU(),
            nn.Linear(32, 64),
            nn.ReLU(),
            nn.Linear(64, input_dim),
            nn.Sigmoid(),
        )
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        encoded = self.encoder(x)
        decoded = self.decoder(encoded)
        return decoded


def train_autoencoder(
    features: np.ndarray,
    config,
) -> Tuple[ExpenseAutoencoder, StandardScaler]:
    """
    Train the autoencoder on the engineered feature set.

    Steps:
      1. StandardScaler normalize features to [0, 1]-ish range
      2. Create DataLoader with batching
      3. Train with MSE loss + Adam optimizer
      4. Save model and scaler to disk

    Args:
        features: 2D numpy array (n_samples, n_features).
        config: Config module with AE_* hyperparameters and TRAINED_MODELS_DIR.

    Returns:
        Tuple of (trained model, fitted scaler).
    """
    input_dim = features.shape[1]
    logger.info(
        "Training autoencoder: %d samples, %d features, latent_dim=%d, epochs=%d",
        features.shape[0], input_dim, config.AE_LATENT_DIM, config.AE_EPOCHS,
    )

    # Normalize features
    scaler = StandardScaler()
    scaled = scaler.fit_transform(features)

    # Clip to reasonable range after scaling (sigmoid output is 0-1)
    scaled = np.clip(scaled, -5, 5)
    # Min-max to [0, 1] for sigmoid output compatibility
    data_min = scaled.min(axis=0)
    data_max = scaled.max(axis=0)
    data_range = data_max - data_min
    data_range[data_range == 0] = 1.0  # Avoid division by zero
    scaled_01 = (scaled - data_min) / data_range

    # Create DataLoader
    tensor_data = torch.FloatTensor(scaled_01)
    dataset = TensorDataset(tensor_data, tensor_data)
    dataloader = DataLoader(
        dataset,
        batch_size=config.AE_BATCH_SIZE,
        shuffle=True,
    )

    # Initialize model
    model = ExpenseAutoencoder(input_dim, config.AE_LATENT_DIM)
    criterion = nn.MSELoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=config.AE_LEARNING_RATE)

    # Training loop
    model.train()
    for epoch in range(config.AE_EPOCHS):
        epoch_loss = 0.0
        for batch_input, batch_target in dataloader:
            optimizer.zero_grad()
            output = model(batch_input)
            loss = criterion(output, batch_target)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item()

        avg_loss = epoch_loss / len(dataloader)
        if (epoch + 1) % 20 == 0 or epoch == 0:
            logger.info("Epoch %d/%d — Loss: %.6f", epoch + 1, config.AE_EPOCHS, avg_loss)

    # Save model and scaler
    model_dir = Path(config.TRAINED_MODELS_DIR)
    model_dir.mkdir(parents=True, exist_ok=True)

    torch.save({
        "model_state_dict": model.state_dict(),
        "input_dim": input_dim,
        "latent_dim": config.AE_LATENT_DIM,
        "data_min": data_min,
        "data_max": data_max,
    }, str(model_dir / "autoencoder.pt"))

    joblib.dump(scaler, str(model_dir / "scaler.pkl"))

    logger.info("Autoencoder saved to %s", model_dir)
    return model, scaler


def load_autoencoder(config) -> Tuple[ExpenseAutoencoder, StandardScaler, dict]:
    """
    Load a trained autoencoder and scaler from disk.

    Returns:
        Tuple of (model, scaler, metadata_dict).
    """
    model_dir = Path(config.TRAINED_MODELS_DIR)
    checkpoint = torch.load(
        str(model_dir / "autoencoder.pt"),
        map_location=torch.device("cpu"),
        weights_only=False,
    )

    model = ExpenseAutoencoder(
        checkpoint["input_dim"],
        checkpoint["latent_dim"],
    )
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()

    scaler = joblib.load(str(model_dir / "scaler.pkl"))

    metadata = {
        "data_min": checkpoint["data_min"],
        "data_max": checkpoint["data_max"],
    }
    return model, scaler, metadata

def get_reconstructed_output(
    model: ExpenseAutoencoder,
    features: np.ndarray,
    scaler: StandardScaler,
    metadata: dict,
) -> np.ndarray:
    """
    Pass features through the autoencoder and return the reconstructed output.
    Args:
        model: Trained autoencoder.
        features: Raw feature matrix (n_samples, n_features).
        scaler: Fitted StandardScaler.
        metadata: Dict with data_min, data_max from training.

    Returns:
        Reconstructed feature matrix as numpy array.
    """
    model.eval()

    # Apply same normalization as training
    scaled = scaler.transform(features)
    scaled = np.clip(scaled, -5, 5)

    data_min = metadata["data_min"]
    data_max = metadata["data_max"]
    data_range = data_max - data_min
    data_range[data_range == 0] = 1.0
    scaled_01 = (scaled - data_min) / data_range

    tensor_input = torch.FloatTensor(scaled_01)

    with torch.no_grad():
        reconstructed = model(tensor_input).numpy()

    return reconstructed


def compute_reconstruction_error(
    original: np.ndarray,
    reconstructed: np.ndarray,
) -> np.ndarray:
    """
    Compute per-sample reconstruction error (MSE).

    Args:
        original: Normalized original features (n_samples, n_features).
        reconstructed: Autoencoder output (n_samples, n_features).

    Returns:
        1D array of MSE values, one per sample.
    """
    return np.mean((original - reconstructed) ** 2, axis=1)
