"""
Dataset Extractor
로그에서 학습/평가 데이터셋 자동 추출
"""
import json
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from collections import Counter, defaultdict
from sqlalchemy.orm import Session
from sqlalchemy import and_, func

from ecommerce.platform.backend.app.database import SessionLocal
from ecommerce.platform.backend.app.router.chatbot_logs.models import (
    ConversationSession,
    ConversationMessage,
    ToolCallLog,
    DatasetSample,
    QualityLabel,
    DatasetType,
    MessageRole
)
from ecommerce.platform.backend.app.router.chatbot_logs.service import LogService


class DatasetExtractor:
    """로그에서 데이터셋 추출"""
    
    def __init__(self, db: Session):
        self.db = db
        self.log_service = LogService(db)
    
    # ============================================
    # 핵심 필터링 로직
    # ============================================
    
    def get_meaningful_sessions(
        self,
        days_back: int = 30,
        min_quality_score: float = 0.6,
        max_samples: int = 1000
    ) -> List[ConversationSession]:
        """
        의미있는 세션 필터링
        
        필터링 기준:
        1. 품질 점수 >= 0.6
        2. 성공적인 도구 호출 포함
        3. 오류율 < 50%
        4. 최근 N일 이내
        """
        cutoff_date = datetime.utcnow() - timedelta(days=days_back)
        
        sessions = self.db.query(ConversationSession).filter(
            and_(
                ConversationSession.created_at >= cutoff_date,
                ConversationSession.quality_score >= min_quality_score,
                ConversationSession.quality_label.in_([
                    QualityLabel.EXCELLENT,
                    QualityLabel.GOOD
                ]),
                # 최소 1번 이상 도구 호출 성공
                ConversationSession.has_successful_tool_call == True,
                # 오류율 < 50%
                ConversationSession.error_count < ConversationSession.turn_count * 0.5
            )
        ).order_by(
            ConversationSession.quality_score.desc(),
            ConversationSession.created_at.desc()
        ).limit(max_samples).all()
        
        return sessions
    
    def apply_diversity_sampling(
        self,
        sessions: List[ConversationSession],
        target_count: int = 500
    ) -> List[ConversationSession]:
        """
        다양성 기반 샘플링
        
        전략:
        1. Intent별 균형
        2. Tool별 균형
        3. 난이도(턴 수) 분포
        """
        if len(sessions) <= target_count:
            return sessions
        
        # Intent 분포 분석
        intent_groups = defaultdict(list)
        for session in sessions:
            messages = self.db.query(ConversationMessage).filter(
                and_(
                    ConversationMessage.session_id == session.id,
                    ConversationMessage.intent.isnot(None)
                )
            ).all()
            
            intents = [m.intent for m in messages]
            primary_intent = Counter(intents).most_common(1)[0][0] if intents else "unknown"
            intent_groups[primary_intent].append(session)
        
        # 각 Intent에서 균등하게 샘플링
        samples_per_intent = target_count // len(intent_groups)
        selected = []
        
        for intent, group in intent_groups.items():
            # 품질 점수 기준 정렬 후 샘플링
            sorted_group = sorted(group, key=lambda s: s.quality_score, reverse=True)
            selected.extend(sorted_group[:samples_per_intent])
        
        # 남은 슬롯은 최고 품질로 채우기
        remaining = target_count - len(selected)
        if remaining > 0:
            all_remaining = [s for s in sessions if s not in selected]
            sorted_remaining = sorted(all_remaining, key=lambda s: s.quality_score, reverse=True)
            selected.extend(sorted_remaining[:remaining])
        
        return selected[:target_count]
    
    def stratified_split(
        self,
        sessions: List[ConversationSession],
        train_ratio: float = 0.7,
        eval_ratio: float = 0.2,
        val_ratio: float = 0.1
    ) -> Dict[DatasetType, List[ConversationSession]]:
        """
        계층적 데이터 분할 (Train/Eval/Val)
        
        Intent별로 비율 유지하며 분할
        """
        assert abs(train_ratio + eval_ratio + val_ratio - 1.0) < 0.01, "비율 합이 1이 아닙니다"
        
        # Intent별 그룹화
        intent_groups = defaultdict(list)
        for session in sessions:
            messages = self.db.query(ConversationMessage).filter(
                and_(
                    ConversationMessage.session_id == session.id,
                    ConversationMessage.intent.isnot(None)
                )
            ).all()
            
            intents = [m.intent for m in messages]
            primary_intent = Counter(intents).most_common(1)[0][0] if intents else "unknown"
            intent_groups[primary_intent].append(session)
        
        # 각 그룹에서 비율대로 분할
        result = {
            DatasetType.TRAINING: [],
            DatasetType.EVALUATION: [],
            DatasetType.VALIDATION: []
        }
        
        for intent, group in intent_groups.items():
            n = len(group)
            train_end = int(n * train_ratio)
            eval_end = train_end + int(n * eval_ratio)
            
            # 품질 점수 기준 정렬 (고품질이 모든 셋에 고르게 분포)
            sorted_group = sorted(group, key=lambda s: s.quality_score, reverse=True)
            
            # 인터리빙 방식으로 분할 (고품질이 모든 셋에 분산)
            for i, session in enumerate(sorted_group):
                if i % 10 < 7:
                    result[DatasetType.TRAINING].append(session)
                elif i % 10 < 9:
                    result[DatasetType.EVALUATION].append(session)
                else:
                    result[DatasetType.VALIDATION].append(session)
        
        return result
    
    # ============================================
    # 데이터셋 생성
    # ============================================
    
    def extract_single_turn_samples(
        self,
        session: ConversationSession
    ) -> List[Dict[str, Any]]:
        """단일 턴 샘플 추출"""
        samples = []
        
        messages = self.db.query(ConversationMessage).filter(
            ConversationMessage.session_id == session.id
        ).order_by(ConversationMessage.turn_number).all()
        
        for i in range(0, len(messages) - 1, 2):
            user_msg = messages[i]
            if i + 1 < len(messages):
                assistant_msg = messages[i + 1]
            else:
                continue
            
            if user_msg.role != MessageRole.USER or assistant_msg.role != MessageRole.ASSISTANT:
                continue
            
            # 도구 호출 정보
            tool_calls = self.db.query(ToolCallLog).filter(
                ToolCallLog.session_id == session.id
            ).all()
            
            sample = {
                "input_text": user_msg.content,
                "expected_output": {
                    "response": assistant_msg.content,
                    "intent": user_msg.intent,
                    "entities": user_msg.entities,
                    "ui_action": assistant_msg.ui_action,
                    "ui_data": assistant_msg.ui_data,
                    "tools_used": [tc.tool_name for tc in tool_calls if tc.execution_status == "success"]
                },
                "context": None,
                "intent": user_msg.intent,
                "tool_name": tool_calls[0].tool_name if tool_calls else None,
                "sample_type": "single_turn"
            }
            
            samples.append(sample)
        
        return samples
    
    def extract_multi_turn_sample(
        self,
        session: ConversationSession
    ) -> Dict[str, Any]:
        """멀티턴 샘플 추출"""
        messages = self.db.query(ConversationMessage).filter(
            ConversationMessage.session_id == session.id
        ).order_by(ConversationMessage.turn_number).all()
        
        turns = []
        for msg in messages:
            turns.append({
                "role": msg.role.value,
                "content": msg.content,
                "intent": msg.intent,
                "entities": msg.entities,
                "ui_action": msg.ui_action
            })
        
        # 도구 호출 시퀀스
        tool_calls = self.db.query(ToolCallLog).filter(
            ToolCallLog.session_id == session.id
        ).order_by(ToolCallLog.created_at).all()
        
        return {
            "conversation_turns": turns,
            "expected_output": {
                "final_status": session.status.value,
                "tools_sequence": [
                    {
                        "tool_name": tc.tool_name,
                        "status": tc.execution_status
                    }
                    for tc in tool_calls
                ]
            },
            "context": {
                "turn_count": session.turn_count,
                "quality_score": session.quality_score
            },
            "sample_type": "multi_turn"
        }
    
    def extract_tool_call_samples(
        self,
        session: ConversationSession
    ) -> List[Dict[str, Any]]:
        """도구 호출 샘플 추출"""
        samples = []
        
        tool_calls = self.db.query(ToolCallLog).filter(
            ToolCallLog.session_id == session.id
        ).all()
        
        messages = self.db.query(ConversationMessage).filter(
            ConversationMessage.session_id == session.id
        ).order_by(ConversationMessage.turn_number).all()
        
        for tc in tool_calls:
            # 해당 도구 호출 직전 사용자 메시지 찾기
            user_msg = None
            for msg in messages:
                if msg.role == MessageRole.USER:
                    user_msg = msg
            
            if not user_msg:
                continue
            
            sample = {
                "input_text": user_msg.content,
                "expected_output": {
                    "tool_name": tc.tool_name,
                    "tool_input": tc.tool_input,
                    "execution_status": tc.execution_status,
                    "validation_required": tc.approval_required
                },
                "context": {
                    "intent": user_msg.intent,
                    "entities": user_msg.entities
                },
                "intent": user_msg.intent,
                "tool_name": tc.tool_name,
                "sample_type": "tool_call"
            }
            
            samples.append(sample)
        
        return samples
    
    def extract_edge_case_samples(
        self,
        session: ConversationSession
    ) -> List[Dict[str, Any]]:
        """엣지 케이스 샘플 추출 (오류 복구 시나리오)"""
        if session.error_count == 0:
            return []
        
        samples = []
        
        messages = self.db.query(ConversationMessage).filter(
            and_(
                ConversationMessage.session_id == session.id,
                ConversationMessage.has_error == True
            )
        ).all()
        
        for error_msg in messages:
            # 오류 메시지와 그 이후 복구 메시지
            recovery_msg = self.db.query(ConversationMessage).filter(
                and_(
                    ConversationMessage.session_id == session.id,
                    ConversationMessage.turn_number > error_msg.turn_number,
                    ConversationMessage.has_error == False
                )
            ).first()
            
            if recovery_msg:
                sample = {
                    "input_text": error_msg.content,
                    "expected_output": {
                        "error_handling": True,
                        "error_type": error_msg.error_message,
                        "recovery_response": recovery_msg.content
                    },
                    "context": {
                        "error_occurred": True
                    },
                    "sample_type": "edge_case",
                    "difficulty_level": "hard"
                }
                
                samples.append(sample)
        
        return samples
    
    # ============================================
    # 메인 추출 함수
    # ============================================
    
    def extract_dataset(
        self,
        days_back: int = 30,
        target_count: int = 500,
        output_format: str = "jsonl"
    ) -> Dict[str, Any]:
        """
        전체 데이터셋 추출 파이프라인
        
        Returns:
            {
                "training": [...],
                "evaluation": [...],
                "validation": [...],
                "stats": {...}
            }
        """
        print(f"📊 데이터셋 추출 시작 (최근 {days_back}일)")
        
        # 1. 의미있는 세션 필터링
        print("1️⃣  의미있는 세션 필터링...")
        meaningful_sessions = self.get_meaningful_sessions(
            days_back=days_back,
            max_samples=target_count * 2  # 넉넉하게
        )
        print(f"   ✓ {len(meaningful_sessions)}개 세션 발견")
        
        # 2. 다양성 샘플링
        print("2️⃣  다양성 기반 샘플링...")
        sampled_sessions = self.apply_diversity_sampling(
            meaningful_sessions,
            target_count=target_count
        )
        print(f"   ✓ {len(sampled_sessions)}개 세션 선택")
        
        # 3. Train/Eval/Val 분할
        print("3️⃣  데이터셋 분할...")
        split_sessions = self.stratified_split(sampled_sessions)
        print(f"   ✓ Train: {len(split_sessions[DatasetType.TRAINING])}")
        print(f"   ✓ Eval: {len(split_sessions[DatasetType.EVALUATION])}")
        print(f"   ✓ Val: {len(split_sessions[DatasetType.VALIDATION])}")
        
        # 4. 샘플 추출
        print("4️⃣  샘플 추출...")
        result = {
            "training": [],
            "evaluation": [],
            "validation": []
        }
        
        stats = {
            "total_sessions": len(sampled_sessions),
            "sample_counts": defaultdict(int),
            "intent_distribution": defaultdict(int),
            "tool_distribution": defaultdict(int)
        }
        
        for dataset_type, sessions in split_sessions.items():
            dataset_key = dataset_type.value
            
            for session in sessions:
                # 단일 턴 샘플
                single_turn_samples = self.extract_single_turn_samples(session)
                result[dataset_key].extend(single_turn_samples)
                stats["sample_counts"]["single_turn"] += len(single_turn_samples)
                
                # 멀티턴 샘플 (3턴 이상만)
                if session.has_multi_turn:
                    multi_turn_sample = self.extract_multi_turn_sample(session)
                    result[dataset_key].append(multi_turn_sample)
                    stats["sample_counts"]["multi_turn"] += 1
                
                # 도구 호출 샘플
                tool_samples = self.extract_tool_call_samples(session)
                result[dataset_key].extend(tool_samples)
                stats["sample_counts"]["tool_call"] += len(tool_samples)
                
                # 엣지 케이스
                edge_samples = self.extract_edge_case_samples(session)
                result[dataset_key].extend(edge_samples)
                stats["sample_counts"]["edge_case"] += len(edge_samples)
                
                # 통계 수집
                for sample in single_turn_samples + tool_samples + edge_samples:
                    if sample.get("intent"):
                        stats["intent_distribution"][sample["intent"]] += 1
                    if sample.get("tool_name"):
                        stats["tool_distribution"][sample["tool_name"]] += 1
        
        print(f"\n✅ 추출 완료!")
        print(f"   📈 총 샘플: {sum(len(v) for v in result.values())}")
        print(f"   - Training: {len(result['training'])}")
        print(f"   - Evaluation: {len(result['evaluation'])}")
        print(f"   - Validation: {len(result['validation'])}")
        
        result["stats"] = dict(stats)
        return result
    
    def save_dataset(
        self,
        dataset: Dict[str, Any],
        output_dir: str = "ecommerce/chatbot/data/extracted_datasets"
    ):
        """데이터셋 저장"""
        import os
        from pathlib import Path
        
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # JSONL 형식으로 저장
        for split in ["training", "evaluation", "validation"]:
            if split in dataset and dataset[split]:
                filepath = output_path / f"{split}_{timestamp}.jsonl"
                with open(filepath, 'w', encoding='utf-8') as f:
                    for sample in dataset[split]:
                        f.write(json.dumps(sample, ensure_ascii=False) + '\n')
                print(f"💾 {split.capitalize()}: {filepath}")
        
        # 통계 저장
        if "stats" in dataset:
            stats_file = output_path / f"stats_{timestamp}.json"
            with open(stats_file, 'w', encoding='utf-8') as f:
                json.dump(dataset["stats"], f, ensure_ascii=False, indent=2)
            print(f"📊 Stats: {stats_file}")


# ============================================
# CLI 실행
# ============================================

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="로그에서 데이터셋 추출")
    parser.add_argument("--days", type=int, default=30, help="최근 N일 데이터 사용")
    parser.add_argument("--count", type=int, default=500, help="목표 샘플 수")
    parser.add_argument("--output", type=str, default="ecommerce/chatbot/data/extracted_datasets", help="출력 디렉토리")
    
    args = parser.parse_args()
    
    db = SessionLocal()
    try:
        extractor = DatasetExtractor(db)
        dataset = extractor.extract_dataset(
            days_back=args.days,
            target_count=args.count
        )
        extractor.save_dataset(dataset, output_dir=args.output)
        
    finally:
        db.close()
