'use client';

import { useState } from 'react';
import styles from './shipping.module.css';

interface Address {
  id: number;
  name: string;
  baseAddress: string;
  detailAddress?: string;
  phone: string;
  isDefault?: boolean;
}

export default function ShippingPage() {
  const [addresses, setAddresses] = useState<Address[]>([
    { id: 1, name: '홍길동', baseAddress: '서울 강남구 테헤란로 123', detailAddress: '101동 202호', phone: '010-1234-5678', isDefault: true },
    { id: 2, name: '김철수', baseAddress: '서울 서초구 서초대로 456', detailAddress: '3층', phone: '010-9876-5432' },
    { id: 3, name: '이영희', baseAddress: '서울 송파구 올림픽로 789', detailAddress: '502호', phone: '010-5555-6666' },
  ]);

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingAddress, setEditingAddress] = useState<Address | null>(null);
  const [formData, setFormData] = useState({ name: '', baseAddress: '', detailAddress: '', phone: '' });

  // 기본 배송지 항상 상단에 정렬
  const sortedAddresses = [...addresses].sort((a, b) => (b.isDefault ? 1 : 0) - (a.isDefault ? 1 : 0));

  const openAddModal = () => {
    setEditingAddress(null);
    setFormData({ name: '', baseAddress: '', detailAddress: '', phone: '' });
    setIsModalOpen(true);
  };

  const openEditModal = (addr: Address) => {
    setEditingAddress(addr);
    setFormData({
      name: addr.name,
      baseAddress: addr.baseAddress,
      detailAddress: addr.detailAddress || '',
      phone: addr.phone,
    });
    setIsModalOpen(true);
  };

  const saveAddress = () => {
    if (!formData.name || !formData.baseAddress || !formData.phone) return;

    if (editingAddress) {
      setAddresses(prev =>
        prev.map(addr =>
          addr.id === editingAddress.id
            ? { ...addr, ...formData }
            : addr
        )
      );
    } else {
      const newId = Math.max(...addresses.map(a => a.id)) + 1;
      setAddresses(prev => [...prev, { id: newId, ...formData }]);
    }
    setIsModalOpen(false);
  };

  const deleteAddress = (id: number) => {
    setAddresses(prev => prev.filter(addr => addr.id !== id));
  };

  const setDefaultAddress = (id: number) => {
    setAddresses(prev =>
      prev.map(addr => ({ ...addr, isDefault: addr.id === id }))
    );
  };

  return (
    <div className={styles.wrapper}>
      <div className={styles.container}>
        <h1 className={styles.title}>배송지 관리</h1>

        <button className={styles.actionButton} onClick={openAddModal}>
          + 배송지 추가
        </button>

        <div className={styles.addressList}>
          {sortedAddresses.map(addr => (
            <div key={addr.id} className={styles.addressBox}>
              <div className={styles.addressDetails}>
                <p>
                  {addr.name} {addr.isDefault && <span className={styles.defaultLabel}>기본</span>}
                </p>
                <p>{addr.baseAddress} {addr.detailAddress && ` / ${addr.detailAddress}`}</p>
                <p>{addr.phone}</p>
              </div>
              <div className={styles.addressActions}>
                {!addr.isDefault && (
                  <button className={styles.actionButton} onClick={() => setDefaultAddress(addr.id)}>기본배송지</button>
                )}
                <button className={styles.actionButton} onClick={() => openEditModal(addr)}>수정</button>
                <button className={styles.actionButton} onClick={() => deleteAddress(addr.id)}>삭제</button>
              </div>
            </div>
          ))}
        </div>

        {/* 배송지 모달 */}
        {isModalOpen && (
          <div className={styles.modalOverlay} onClick={() => setIsModalOpen(false)}>
            <div className={styles.modalContent} onClick={e => e.stopPropagation()}>
              <h2>{editingAddress ? '배송지 수정' : '배송지 추가'}</h2>
              <div className={styles.newAddressForm}>
                <input
                  type="text"
                  placeholder="수령인 이름"
                  value={formData.name}
                  onChange={e => setFormData({...formData, name: e.target.value})}
                />
                <input
                  type="text"
                  placeholder="기본 주소"
                  value={formData.baseAddress}
                  onChange={e => setFormData({...formData, baseAddress: e.target.value})}
                />
                <input
                  type="text"
                  placeholder="상세 주소"
                  value={formData.detailAddress}
                  onChange={e => setFormData({...formData, detailAddress: e.target.value})}
                />
                <input
                  type="text"
                  placeholder="전화번호"
                  value={formData.phone}
                  onChange={e => setFormData({...formData, phone: e.target.value})}
                />
              </div>
              <div className={styles.modalButtons}>
                <button className={styles.actionButton} onClick={() => setIsModalOpen(false)}>취소</button>
                <button className={styles.actionButton} onClick={saveAddress}>저장</button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
