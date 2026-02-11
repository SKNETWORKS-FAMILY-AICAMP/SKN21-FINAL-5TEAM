'use client';

import { useState, useEffect } from 'react';
import styles from './shipping.module.css';

interface ShippingAddress {
  id: number;
  recipient_name: string;
  address1: string;
  address2: string;
  post_code: string;
  phone: string;
  is_default?: boolean;
}

export default function ShippingPage() {
  const [addresses, setAddresses] = useState<ShippingAddress[]>([]);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingAddress, setEditingAddress] = useState<ShippingAddress | null>(null);
  const [formData, setFormData] = useState({
    recipient_name: '',
    address1: '',
    address2: '',
    post_code: '',
    phone: '',
  });

  const API_BASE = 'http://localhost:8000/shipping';

  // =====================
  // 배송지 목록 가져오기
  // =====================
  const fetchAddresses = async () => {
    try {
      const res = await fetch(`${API_BASE}?user_id=1`);
      if (!res.ok) throw new Error('배송지 가져오기 실패');
      const data: ShippingAddress[] = await res.json();
      setAddresses(data);
    } catch (err) {
      console.error(err);
    }
  };

  useEffect(() => {
    fetchAddresses();
  }, []);

  // =====================
  // 기본 배송지 상단 정렬
  // =====================
  const sortedAddresses = [...addresses].sort((a, b) => (b.is_default ? 1 : 0) - (a.is_default ? 1 : 0));

  // =====================
  // 모달 열기
  // =====================
  const openAddModal = () => {
    setEditingAddress(null);
    setFormData({ recipient_name: '', address1: '', address2: '', post_code: '', phone: '' });
    setIsModalOpen(true);
  };

  const openEditModal = (addr: ShippingAddress) => {
    setEditingAddress(addr);
    setFormData({
      recipient_name: addr.recipient_name,
      address1: addr.address1,
      address2: addr.address2 || '',
      post_code: addr.post_code || '',
      phone: addr.phone,
    });
    setIsModalOpen(true);
  };

  // =====================
  // 주소 저장 (추가/수정)
  // =====================
  const saveAddress = async () => {
    if (!formData.recipient_name || !formData.address1 || !formData.phone) return;

    try {
      const payload = {
        recipient_name: formData.recipient_name,
        address1: formData.address1,
        address2: formData.address2 || "",
        post_code: formData.post_code || "",
        phone: formData.phone,
        is_default: editingAddress ? Boolean(editingAddress.is_default) : false, // boolean 전송
      };

      let res;
      if (editingAddress) {
        res = await fetch(`${API_BASE}/${editingAddress.id}`, {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      } else {
        res = await fetch(`${API_BASE}?user_id=1`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
      }

      if (!res.ok) throw new Error('저장 실패');
      await fetchAddresses();
      setIsModalOpen(false);
    } catch (err) {
      console.error(err);
    }
  };

  // =====================
  // 주소 삭제
  // =====================
  const deleteAddress = async (id: number) => {
    try {
      const res = await fetch(`${API_BASE}/${id}`, { method: 'DELETE' });
      if (!res.ok) throw new Error('삭제 실패');
      await fetchAddresses();
    } catch (err) {
      console.error(err);
    }
  };

  // =====================
  // 기본 배송지 설정
  // =====================
  const setDefaultAddress = async (id: number) => {
    try {
      const res = await fetch(`${API_BASE}/${id}/default`, { method: 'PATCH' });
      if (!res.ok) throw new Error('기본 배송지 설정 실패');
      await fetchAddresses();
    } catch (err) {
      console.error(err);
    }
  };

  // =====================
  // 렌더링
  // =====================
  return (
    <div className={styles.wrapper}>
      <div className={styles.container}>
        <h1 className={styles.title}>배송지 관리</h1>
        <button className={styles.actionButton} onClick={openAddModal}>+ 배송지 추가</button>

        <div className={styles.addressList}>
          {sortedAddresses.map(addr => (
            <div key={addr.id} className={styles.addressBox}>
              <div className={styles.addressDetails}>
                <p>
                  {addr.recipient_name} {addr.is_default && <span className={styles.defaultLabel}>기본</span>}
                </p>
                <p>({addr.post_code}) {addr.address1} {addr.address2 && ` / ${addr.address2}`}</p>
                <p>{addr.phone}</p>
              </div>
              <div className={styles.addressActions}>
                {!addr.is_default && (
                  <button className={styles.actionButton} onClick={() => setDefaultAddress(addr.id)}>기본배송지</button>
                )}
                <button className={styles.actionButton} onClick={() => openEditModal(addr)}>수정</button>
                <button className={styles.actionButton} onClick={() => deleteAddress(addr.id)}>삭제</button>
              </div>
            </div>
          ))}
        </div>

        {/* 모달 */}
        {isModalOpen && (
          <div className={styles.modalOverlay} onClick={() => setIsModalOpen(false)}>
            <div className={styles.modalContent} onClick={e => e.stopPropagation()}>
              <h2>{editingAddress ? '배송지 수정' : '배송지 추가'}</h2>
              <div className={styles.newAddressForm}>
                <input
                  type="text"
                  placeholder="수령인 이름"
                  value={formData.recipient_name}
                  onChange={e => setFormData({ ...formData, recipient_name: e.target.value })}
                />
                <input
                  type="text"
                  placeholder="우편번호"
                  value={formData.post_code}
                  onChange={e => setFormData({ ...formData, post_code: e.target.value })}
                />
                <input
                  type="text"
                  placeholder="기본 주소"
                  value={formData.address1}
                  onChange={e => setFormData({ ...formData, address1: e.target.value })}
                />
                <input
                  type="text"
                  placeholder="상세 주소"
                  value={formData.address2}
                  onChange={e => setFormData({ ...formData, address2: e.target.value })}
                />
                <input
                  type="text"
                  placeholder="전화번호"
                  value={formData.phone}
                  onChange={e => setFormData({ ...formData, phone: e.target.value })}
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
