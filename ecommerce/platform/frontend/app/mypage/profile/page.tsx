'use client';

import { useState } from 'react';
import styles from './profile.module.css';

type ModalType =
  | 'profile'
  | 'password'
  | 'style'
  | 'address'
  | 'alarm'
  | 'withdraw'
  | null;

export default function ProfilePage() {
  const [openModal, setOpenModal] = useState<ModalType>(null);
  const [withdrawReason, setWithdrawReason] = useState('');

  const closeModal = () => setOpenModal(null);

  return (
    <div className={styles.page}>
      <div className={styles.container}>
        <h2 className={styles.title}>설정</h2>

        {/* 프로필 */}
        <div className={styles.profileBox}>
          <div className={styles.avatar} />
          <div>
            <strong className={styles.userName}>윈터는 이쁘다</strong>
            <p className={styles.userId}>ID: abcd1234</p>
          </div>
        </div>

        <div className={styles.buttonRow}>
          <button className={styles.outlineBtn}>프로필 이미지 변경</button>
          <button className={styles.outlineBtn}>닉네임 변경</button>
        </div>

        {/* 메뉴 */}
        <ul className={styles.menuList}>
          <li className={styles.menuItem} onClick={() => setOpenModal('profile')}>
            <div>
              <strong>회원정보 변경</strong>
              <p>이름, 휴대폰번호, 이메일</p>
            </div>
            <span className={styles.arrow}>›</span>
          </li>

          <li className={styles.menuItem} onClick={() => setOpenModal('password')}>
            <strong>비밀번호 변경</strong>
            <span className={styles.arrow}>›</span>
          </li>

          <li className={styles.menuItem} onClick={() => setOpenModal('style')}>
            <strong>나의 맞춤 정보</strong>
            <span className={styles.arrow}>›</span>
          </li>

          <li className={styles.menuItem} onClick={() => setOpenModal('address')}>
            <strong>배송지 관리</strong>
            <span className={styles.arrow}>›</span>
          </li>

          <li className={styles.menuItem} onClick={() => setOpenModal('alarm')}>
            <strong>알림 설정</strong>
            <span className={styles.arrow}>›</span>
          </li>

          <li className={styles.menuItem} onClick={() => setOpenModal('withdraw')}>
            <strong>회원 탈퇴</strong>
            <span className={styles.arrow}>›</span>
          </li>
        </ul>

        {/* ===== 모달 ===== */}
        {openModal && (
          <>
            <div className={styles.dim} onClick={closeModal} />
            <div
              className={styles.modal}
              onClick={(e) => e.stopPropagation()}
            >
              {/* 회원정보 변경 */}
              {openModal === 'profile' && (
                <>
                  <h3>회원정보 변경</h3>
                  <input placeholder="이름" />
                  <input placeholder="이메일" />
                  <input placeholder="휴대폰번호" />
                </>
              )}

              {/* 비밀번호 변경 */}
              {openModal === 'password' && (
                <>
                  <h3>비밀번호 변경</h3>
                  <input type="password" placeholder="현재 비밀번호" />
                  <input type="password" placeholder="새 비밀번호" />
                  <input type="password" placeholder="비밀번호 확인" />
                </>
              )}

              {/* 나의 맞춤 정보 */}
              {openModal === 'style' && (
                <>
                  <h3>나의 맞춤 정보</h3>
                  <input placeholder="키 (cm)" />
                  <input placeholder="몸무게 (kg)" />
                </>
              )}

              {/* 배송지 관리 */}
              {openModal === 'address' && (
                <>
                  <h3>배송지 관리</h3>
                  <button className={styles.addBtn}>배송지 추가하기</button>
                  <div className={styles.box}>
                    서울시 강남구 테헤란로 123
                  </div>
                </>
              )}

              {/* 알림 설정 */}
              {openModal === 'alarm' && (
                <>
                  <h3>알림 설정</h3>
                  <div className={styles.toggleRow}>
                    <span>마케팅 목적 개인정보 수집 동의(선택)</span>
                    <input type="checkbox" />
                  </div>
                  <div className={styles.toggleRow}>
                    <span>문자 수신</span>
                    <input type="checkbox" />
                  </div>
                  <div className={styles.toggleRow}>
                    <span>이메일 수신</span>
                    <input type="checkbox" />
                  </div>
                </>
              )}

              {/* 회원 탈퇴 */}
              {openModal === 'withdraw' && (
                <>
                  <h3>회원 탈퇴</h3>
                  <p className={styles.desc}>
                    탈퇴 사유를 선택해 주세요.
                  </p>
                  <select
                    value={withdrawReason}
                    onChange={(e) => setWithdrawReason(e.target.value)}
                  >
                    <option value="">선택해주세요</option>
                    <option>구매할 만한 상품이 없어요.</option>
                    <option>상품 가격이 비싸요.</option>
                    <option>배송이 느려요.</option>
                    <option>교환/환불이 불편해요.</option>
                    <option>혜택이 부족해요.</option>
                    <option>기타</option>
                  </select>

                  <div className={styles.modalButtons}>
                    <button className={styles.cancel} onClick={closeModal}>
                      탈퇴 그만두기
                    </button>
                    <button
                      className={styles.confirm}
                      disabled={!withdrawReason}
                    >
                      다음
                    </button>
                  </div>
                </>
              )}

              {/* 공통 버튼 */}
              {openModal !== 'withdraw' && (
                <div className={styles.modalButtons}>
                  <button className={styles.cancel} onClick={closeModal}>
                    취소
                  </button>
                  <button className={styles.confirm} onClick={closeModal}>
                    저장
                  </button>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </div>
  );
}
