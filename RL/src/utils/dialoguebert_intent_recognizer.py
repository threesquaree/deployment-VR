"""
DialogueBERT Intent Recognition Module

This module provides DialogueBERT-based intent recognition for the HRL museum 
dialogue agent. DialogueBERT uses contextual encoders that interpret utterances 
in light of speaker role and local dialogue history.

Paper: "DialogueBERT: A Self-Supervised Learning based Dialogue Pre-training Encoder"
by Zhang et al., 2021.

Key Features:
- Turn-aware encoding for multi-turn dialogues
- Role-specific token integration (user/system)
- Dialogue context tracking
- Robust intent recognition in conversational settings
"""

import torch
import numpy as np
from transformers import AutoTokenizer, AutoModel
from typing import List, Dict, Any, Optional, Tuple
import logging
import os

from src.utils.dialoguebert_model import DialogueBERTModel

logger = logging.getLogger(__name__)


class DialogueBERTIntentRecognizer:
    """
    DialogueBERT based intent recognition for museum dialogue agent.
    
    Implements DialogueBERT architecture (Zhang et al. 2021) with:
    - Turn embeddings: Track turn position in dialogue (0-indexed)
    - Role embeddings: Distinguish user (0) vs system/agent (1)
    
    DialogueBERT advantages over standard BERT:
    - Turn-order and role encoding for dialogue context
    - Multi-turn conversation understanding
    - Better intent recognition accuracy in dialogues
    - Dialogue state tracking capabilities
    
    Architecture:
    - Base model: BERT (bert-base-uncased) with pre-trained weights
    - Additional embeddings: Turn embedding (50 turns) + Role embedding (2 roles)
    - Final embedding = TokenEmbedding + PositionEmbedding + TurnEmbedding + RoleEmbedding
    """
    
    def __init__(self, model_name: str = "bert-base-uncased", 
                 device: Optional[str] = None,
                 mode: str = "dialoguebert"):
        """
        Initialize DialogueBERT intent recognizer.
        
        Loads DialogueBERT model with turn and role embeddings, or standard BERT
        depending on mode parameter.
        
        Args:
            model_name: HuggingFace model name for base BERT model (default: bert-base-uncased)
            device: Device to run model on ('cpu', 'cuda', or None for auto)
            mode: "dialoguebert" (default) for DialogueBERT with turn/role embeddings,
                  "standard_bert" for standard BERT without turn/role embeddings
        """
        self.model_name = model_name
        self.device = device or ('cuda' if torch.cuda.is_available() else 'cpu')
        self.mode = mode.lower()
        
        # Check if we should use offline mode (skip model loading)
        if os.environ.get('TRANSFORMERS_OFFLINE') == '1' or os.environ.get('HRL_FAST_MODE') == '1':
            logger.info("FAST MODE: Using fallback embeddings (no model loading)")
            self.model = None
            self.tokenizer = None
            return
        
        try:
            # Load tokenizer (same for both modes)
            self.tokenizer = AutoTokenizer.from_pretrained(model_name)
            
            if self.mode == "standard_bert":
                # Load standard BERT model (no turn/role embeddings)
                self.model = AutoModel.from_pretrained(model_name)
                self.model.to(self.device)
                self.model.eval()
                logger.info(f"Standard BERT loaded successfully on {self.device}")
                logger.info(f"Model: {model_name} (standard BERT, no turn/role embeddings)")
            else:
                # Load DialogueBERT model with turn and role embeddings
                self.model = DialogueBERTModel(
                    base_model_name=model_name,
                    max_turns=50,  # Support up to 50 turns
                    embedding_dim=768  # BERT-base embedding dimension
                )
                self.model.to(self.device)
                self.model.eval()
                logger.info(f"DialogueBERT loaded successfully on {self.device}")
                logger.info(f"Model: {model_name} with turn/role embeddings")
            
        except Exception as e:
            logger.error(f"Failed to load model: {e}")
            logger.info("Falling back to rule-based embeddings")
            self.model = None
            self.tokenizer = None
    
    def _load_fallback_model(self):
        """Load fallback BERT model if DialogueBERT fails."""
        try:
            self.tokenizer = AutoTokenizer.from_pretrained("bert-base-uncased")
            self.model = AutoModel.from_pretrained("bert-base-uncased")
            self.model.to(self.device)
            self.model.eval()
            logger.info("Fallback BERT model loaded")
        except Exception as e:
            logger.error(f"Failed to load fallback model: {e}")
            self.model = None
            self.tokenizer = None
    
    def get_intent_embedding(self, utterance: str, role: str = "user", 
                            turn_number: Optional[int] = None) -> np.ndarray:
        """
        Generate intent embedding for a visitor utterance.
        
        Uses DialogueBERT (with turn/role embeddings) or standard BERT depending on mode.
        
        Args:
            utterance: Visitor's utterance text
            role: Speaker role ("user" or "system")
            turn_number: Turn number in dialogue (0-indexed, optional)
            
        Returns:
            Intent embedding vector of shape (768,)
        """
        if not utterance or not utterance.strip():
            return self._get_silence_embedding()
        
        if self.model is None:
            return self._fallback_intent_embedding(utterance)
        
        try:
            if self.mode == "standard_bert":
                # Standard BERT: tokenize and get [CLS] token (no turn/role embeddings)
                inputs = self.tokenizer(
                    utterance,
                    return_tensors="pt",
                    add_special_tokens=True,
                    truncation=True,
                    max_length=512,
                    padding=True
                )
                input_ids = inputs['input_ids'].to(self.device)
                attention_mask = inputs.get('attention_mask', None)
                if attention_mask is not None:
                    attention_mask = attention_mask.to(self.device)
                
                with torch.no_grad():
                    outputs = self.model(
                        input_ids=input_ids,
                        attention_mask=attention_mask,
                        return_dict=True
                    )
                    # Get [CLS] token embedding
                    intent_embedding = outputs.last_hidden_state[:, 0, :]
                
                return intent_embedding.cpu().numpy().flatten()
            else:
                # DialogueBERT: use turn and role embeddings
                inputs = self.tokenizer(
                    utterance,
                    return_tensors="pt",
                    add_special_tokens=True,
                    truncation=True,
                    max_length=512,
                    padding=True
                )
                
                input_ids = inputs['input_ids'].to(self.device)
                attention_mask = inputs.get('attention_mask', None)
                if attention_mask is not None:
                    attention_mask = attention_mask.to(self.device)
                
                batch_size, seq_len = input_ids.shape
                
                # Turn IDs: use turn_number if provided, else default to 0
                if turn_number is not None:
                    turn_ids = torch.full((batch_size, seq_len), turn_number, dtype=torch.long, device=self.device)
                else:
                    turn_ids = torch.zeros((batch_size, seq_len), dtype=torch.long, device=self.device)
                
                # Role IDs: 0 = user, 1 = system/agent
                role_id = 0 if role.lower() == "user" else 1
                role_ids = torch.full((batch_size, seq_len), role_id, dtype=torch.long, device=self.device)
                
                # Generate embeddings with DialogueBERT (includes turn and role embeddings)
                with torch.no_grad():
                    intent_embedding = self.model.get_pooled_output(
                        input_ids=input_ids,
                        attention_mask=attention_mask,
                        turn_ids=turn_ids,
                        role_ids=role_ids
                    )
                
                return intent_embedding.cpu().numpy().flatten()
            
        except Exception as e:
            logger.warning(f"Error generating intent embedding: {e}")
            return self._fallback_intent_embedding(utterance)
    
    def get_dialogue_context(self, recent_utterances: List[Tuple[str, str, int]], 
                           max_turns: int = 3) -> np.ndarray:
        """
        Generate dialogue context embedding.
        
        Uses DialogueBERT (with turn/role embeddings) or standard BERT depending on mode.
        
        Args:
            recent_utterances: List of (role, text, turn_number) tuples
            max_turns: Maximum number of turns to include
            
        Returns:
            Dialogue context embedding vector of shape (768,)
        """
        if not recent_utterances:
            return self._get_empty_context_embedding()
        
        if self.model is None:
            # Extract just text for fallback
            texts = [u[1] if len(u) >= 2 else u[0] for u in recent_utterances]
            return self._fallback_context_embedding(texts)
        
        try:
            # Take last max_turns utterances
            context_utterances = recent_utterances[-max_turns:]
            
            # Build dialogue text
            dialogue_parts = []
            turn_numbers = []
            role_ids_list = []
            
            for utterance_tuple in context_utterances:
                if len(utterance_tuple) == 3:
                    role, text, turn_num = utterance_tuple
                elif len(utterance_tuple) == 2:
                    # Backward compatibility: (role, text)
                    role, text = utterance_tuple
                    turn_num = 0
                else:
                    continue
                
                dialogue_parts.append(text)
                turn_numbers.append(turn_num)
                role_id = 0 if role.lower() == "user" else 1
                role_ids_list.append(role_id)
            
            # Join utterances with [SEP] token
            context_text = " [SEP] ".join(dialogue_parts)
            
            # Tokenize
            inputs = self.tokenizer(
                context_text,
                return_tensors="pt",
                add_special_tokens=True,
                truncation=True,
                max_length=512,
                padding=True
            )
            
            input_ids = inputs['input_ids'].to(self.device)
            attention_mask = inputs.get('attention_mask', None)
            if attention_mask is not None:
                attention_mask = attention_mask.to(self.device)
            
            if self.mode == "standard_bert":
                # Standard BERT: just get [CLS] token (no turn/role embeddings)
                with torch.no_grad():
                    outputs = self.model(
                        input_ids=input_ids,
                        attention_mask=attention_mask,
                        return_dict=True
                    )
                    context_embedding = outputs.last_hidden_state[:, 0, :]
                
                return context_embedding.cpu().numpy().flatten()
            else:
                # DialogueBERT: use turn and role embeddings
                batch_size, seq_len = input_ids.shape
                
                # For multi-utterance context, use average turn number
                avg_turn = int(sum(turn_numbers) / len(turn_numbers)) if turn_numbers else 0
                turn_ids = torch.full((batch_size, seq_len), avg_turn, dtype=torch.long, device=self.device)
                
                # Use role of the last utterance
                last_role_id = role_ids_list[-1] if role_ids_list else 0
                role_ids = torch.full((batch_size, seq_len), last_role_id, dtype=torch.long, device=self.device)
                
                # Generate context embedding with DialogueBERT
                with torch.no_grad():
                    context_embedding = self.model.get_pooled_output(
                        input_ids=input_ids,
                        attention_mask=attention_mask,
                        turn_ids=turn_ids,
                        role_ids=role_ids
                    )
                
                return context_embedding.cpu().numpy().flatten()
            
        except Exception as e:
            logger.warning(f"Error generating context embedding: {e}")
            texts = [u[1] if len(u) >= 2 else u[0] for u in recent_utterances]
            return self._fallback_context_embedding(texts)
    
    def classify_intent_category(self, utterance: str) -> str:
        """
        Classify utterance into intent categories using DialogueBERT understanding.
        
        Args:
            utterance: Visitor utterance
            
        Returns:
            Intent category string
        """
        if not utterance or not utterance.strip():
            return "silence"
        
        utterance_lower = utterance.lower()
        
        # Question indicators
        if any(word in utterance_lower for word in ["?", "what", "how", "why", "when", "where", "who", "which"]):
            return "question"
        
        # Confusion indicators
        if any(word in utterance_lower for word in ["don't understand", "confused", "unclear", "what do you mean", "huh", "what"]):
            return "confusion"
        
        # Interest indicators
        if any(word in utterance_lower for word in ["interesting", "fascinating", "amazing", "wow", "beautiful", "love", "like"]):
            return "interest"
        
        # Request indicators
        if any(word in utterance_lower for word in ["tell me", "explain", "show me", "can you", "could you"]):
            return "request"
        
        # Default to statement
        return "statement"
    
    def get_dialogue_state_embedding(self, current_state: Dict[str, Any]) -> np.ndarray:
        """
        Generate dialogue state embedding for tracking conversation state.
        
        Args:
            current_state: Current dialogue state dictionary
            
        Returns:
            State embedding vector of shape (768,)
        """
        if self.model is None:
            return self._get_empty_context_embedding()
        
        try:
            # Build state description
            state_parts = []
            
            if current_state.get("current_focus"):
                state_parts.append(f"Focus: {current_state['current_focus']}")
            
            if current_state.get("explained_exhibits"):
                state_parts.append(f"Explained: {', '.join(current_state['explained_exhibits'])}")
            
            if current_state.get("recent_actions"):
                state_parts.append(f"Actions: {', '.join(current_state['recent_actions'])}")
            
            state_text = " [SEP] ".join(state_parts) if state_parts else "Initial state"
            
            # Tokenize with DialogueBERT approach
            inputs = self.tokenizer(
                state_text,
                return_tensors="pt",
                add_special_tokens=True,
                truncation=True,
                max_length=256,
                padding=True
            )
            
            # Move inputs to device
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            
            # Generate state embedding
            with torch.no_grad():
                outputs = self.model(**inputs)
                state_embedding = outputs.last_hidden_state[:, 0, :].cpu().numpy()
            
            return state_embedding.flatten()
            
        except Exception as e:
            logger.warning(f"Error generating state embedding: {e}")
            return self._get_empty_context_embedding()
    
    def _get_silence_embedding(self) -> np.ndarray:
        """Generate embedding for silence/empty utterances."""
        return np.zeros(768, dtype=np.float32)
    
    def _get_empty_context_embedding(self) -> np.ndarray:
        """Generate embedding for empty dialogue context."""
        return np.zeros(768, dtype=np.float32)
    
    def _fallback_intent_embedding(self, utterance: str) -> np.ndarray:
        """
        Fallback intent embedding when DialogueBERT is not available.
        
        Args:
            utterance: Visitor utterance
            
        Returns:
            Simple intent embedding
        """
        # Simple one-hot encoding based on intent classification
        intent_category = self.classify_intent_category(utterance)
        
        # Create simple embedding (could be enhanced)
        embedding = np.zeros(768, dtype=np.float32)
        
        # Set some values based on intent category
        if intent_category == "question":
            embedding[:100] = 0.1
        elif intent_category == "confusion":
            embedding[100:200] = 0.1
        elif intent_category == "interest":
            embedding[200:300] = 0.1
        elif intent_category == "request":
            embedding[300:400] = 0.1
        elif intent_category == "statement":
            embedding[400:500] = 0.1
        # silence remains all zeros
        
        return embedding
    
    def _fallback_context_embedding(self, utterances: List[str]) -> np.ndarray:
        """
        Fallback context embedding when DialogueBERT is not available.
        
        Args:
            utterances: List of recent utterances
            
        Returns:
            Simple context embedding
        """
        # Simple context embedding based on utterance count and types
        embedding = np.zeros(768, dtype=np.float32)
        
        if not utterances:
            return embedding
        
        # Encode basic context information
        num_utterances = len(utterances)
        embedding[500:600] = num_utterances / 10.0  # Normalize by max expected turns
        
        # Encode recent intent patterns
        recent_intents = [self.classify_intent_category(u) for u in utterances[-3:]]
        
        if "question" in recent_intents:
            embedding[600:650] = 0.1
        if "confusion" in recent_intents:
            embedding[650:700] = 0.1
        if "interest" in recent_intents:
            embedding[700:750] = 0.1
        
        return embedding


# Global DialogueBERT intent recognizer instance
_dialoguebert_recognizer = None


def get_dialoguebert_recognizer() -> DialogueBERTIntentRecognizer:
    """
    Get global DialogueBERT recognizer instance (singleton pattern).
    
    Checks environment variable HRL_BERT_MODE:
    - HRL_BERT_MODE=standard → use standard BERT mode
    - HRL_BERT_MODE=dialoguebert or unset → use DialogueBERT mode (default)
    
    Returns:
        DialogueBERTIntentRecognizer instance
    """
    global _dialoguebert_recognizer
    if _dialoguebert_recognizer is None:
        # Check environment variable for mode
        bert_mode = os.environ.get('HRL_BERT_MODE', 'dialoguebert').lower()
        if bert_mode == 'standard':
            mode = 'standard_bert'
        else:
            mode = 'dialoguebert'
        _dialoguebert_recognizer = DialogueBERTIntentRecognizer(mode=mode)
    return _dialoguebert_recognizer


def reset_dialoguebert_recognizer():
    """Reset global DialogueBERT recognizer instance."""
    global _dialoguebert_recognizer
    _dialoguebert_recognizer = None
