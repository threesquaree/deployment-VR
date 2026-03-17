"""
DialogueBERT Model Architecture

Implements DialogueBERT (Zhang et al. 2021) with turn and role embeddings
for dialogue understanding. Extends BERT with dialogue-specific features:
- Turn embeddings: Track position in dialogue (0-indexed, max 50 turns)
- Role embeddings: Distinguish user (0) vs system/agent (1)

Based on: "DialogueBERT: A Self-Supervised Learning based Dialogue Pre-training Encoder"
by Zhang et al., 2021 (arXiv:2109.10480)

Architecture:
- Base: Pre-trained BERT (bert-base-uncased) with frozen or trainable weights
- Turn embedding: nn.Embedding(max_turns=50, embedding_dim=768)
- Role embedding: nn.Embedding(num_roles=2, embedding_dim=768)
- Combined: TokenEmbedding + PositionEmbedding + TurnEmbedding + RoleEmbedding

Note: Since pre-trained DialogueBERT weights are not publicly available,
we initialize with BERT weights and add turn/role embeddings with random initialization.
"""

import torch
import torch.nn as nn
from transformers import BertModel, BertConfig
from typing import Optional, Tuple


class DialogueBERTModel(nn.Module):
    """
    DialogueBERT model with turn and role embeddings.
    
    Extends BERT with:
    - Turn embeddings: Track turn position in dialogue (0-indexed)
    - Role embeddings: Distinguish user (0) vs system/agent (1)
    
    Architecture:
    Final embedding = TokenEmbedding + PositionEmbedding + TurnEmbedding + RoleEmbedding
    """
    
    def __init__(self, base_model_name: str = "bert-base-uncased", 
                 max_turns: int = 50,
                 embedding_dim: int = 768):
        """
        Initialize DialogueBERT model.
        
        Args:
            base_model_name: HuggingFace model name for base BERT
            max_turns: Maximum number of turns to support (for turn embedding size)
            embedding_dim: Embedding dimension (768 for BERT-base)
        """
        super().__init__()
        
        # Load base BERT model
        self.bert = BertModel.from_pretrained(base_model_name)
        self.config = self.bert.config
        self.embedding_dim = embedding_dim
        
        # Turn embedding: maps turn number (0 to max_turns-1) to embedding vector
        self.turn_embedding = nn.Embedding(max_turns, embedding_dim)
        
        # Role embedding: maps role (0=user, 1=system) to embedding vector
        self.role_embedding = nn.Embedding(2, embedding_dim)
        
        # Initialize turn and role embeddings
        # Turn embeddings: small random initialization
        nn.init.normal_(self.turn_embedding.weight, mean=0.0, std=0.02)
        
        # Role embeddings: small random initialization
        nn.init.normal_(self.role_embedding.weight, mean=0.0, std=0.02)
        
        self.max_turns = max_turns
        
    def forward(self, input_ids: torch.Tensor,
                attention_mask: Optional[torch.Tensor] = None,
                turn_ids: Optional[torch.Tensor] = None,
                role_ids: Optional[torch.Tensor] = None,
                token_type_ids: Optional[torch.Tensor] = None) -> torch.Tensor:
        """
        Forward pass through DialogueBERT.
        
        Args:
            input_ids: Token IDs from tokenizer [batch_size, seq_len]
            attention_mask: Attention mask [batch_size, seq_len]
            turn_ids: Turn numbers for each token [batch_size, seq_len] (0-indexed)
            role_ids: Role IDs for each token [batch_size, seq_len] (0=user, 1=system)
            token_type_ids: BERT token type IDs (optional, for compatibility)
            
        Returns:
            Last hidden state from BERT with DialogueBERT embeddings [batch_size, seq_len, hidden_dim]
        """
        # Get BERT embeddings (token + position embeddings)
        bert_outputs = self.bert(
            input_ids=input_ids,
            attention_mask=attention_mask,
            token_type_ids=token_type_ids,
            return_dict=True
        )
        
        # BERT embeddings: [batch_size, seq_len, hidden_dim]
        hidden_states = bert_outputs.last_hidden_state
        batch_size, seq_len, _ = hidden_states.shape
        
        # Add turn embeddings (always add, use provided or default to 0)
        if turn_ids is not None:
            # Clamp turn_ids to valid range [0, max_turns-1]
            turn_ids = torch.clamp(turn_ids, 0, self.max_turns - 1)
        else:
            # Default to turn 0 if not provided
            turn_ids = torch.zeros((batch_size, seq_len), dtype=torch.long, device=hidden_states.device)
        
        turn_embeds = self.turn_embedding(turn_ids)  # [batch_size, seq_len, hidden_dim]
        hidden_states = hidden_states + turn_embeds
        
        # Add role embeddings (always add, use provided or default to 0=user)
        if role_ids is not None:
            # Ensure role_ids are 0 or 1
            role_ids = torch.clamp(role_ids, 0, 1)
        else:
            # Default to role 0 (user) if not provided
            role_ids = torch.zeros((batch_size, seq_len), dtype=torch.long, device=hidden_states.device)
        
        role_embeds = self.role_embedding(role_ids)  # [batch_size, seq_len, hidden_dim]
        hidden_states = hidden_states + role_embeds
        
        return hidden_states
    
    def get_pooled_output(self, input_ids: torch.Tensor,
                         attention_mask: Optional[torch.Tensor] = None,
                         turn_ids: Optional[torch.Tensor] = None,
                         role_ids: Optional[torch.Tensor] = None,
                         token_type_ids: Optional[torch.Tensor] = None) -> torch.Tensor:
        """
        Get pooled output (CLS token) with DialogueBERT embeddings.
        
        Args:
            Same as forward()
            
        Returns:
            Pooled representation [batch_size, hidden_dim]
        """
        hidden_states = self.forward(
            input_ids=input_ids,
            attention_mask=attention_mask,
            turn_ids=turn_ids,
            role_ids=role_ids,
            token_type_ids=token_type_ids
        )
        
        # Return [CLS] token (first token)
        return hidden_states[:, 0, :]
    
    def freeze_bert(self):
        """Freeze BERT weights, only train turn/role embeddings."""
        for param in self.bert.parameters():
            param.requires_grad = False
    
    def unfreeze_bert(self):
        """Unfreeze BERT weights for fine-tuning."""
        for param in self.bert.parameters():
            param.requires_grad = True

