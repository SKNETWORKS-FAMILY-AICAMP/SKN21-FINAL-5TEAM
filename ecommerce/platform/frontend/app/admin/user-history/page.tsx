'use client';

import { useState, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '../../authcontext';
import styles from './admin-history.module.css';

// ============================================
// Types
// ============================================

interface User {
  id: number;
  email: string;
  name: string;
  created_at: string;
}

type ActionType =
  | 'all'
  | 'login'
  | 'logout'
  | 'cart_add'
  | 'cart_remove'
  | 'order_create'
  | 'order_cancel'
  | 'refund_request'
  | 'review_create';

interface UserHistory {
  id: number;
  user_id: number;
  action_type: string;
  product_option_type: string | null;
  product_option_id: number | null;
  order_id: number | null;
  cart_item_id: number | null;
  action_metadata: string | null;
  search_keyword: string | null;
  ip_address: string | null;
  user_agent: string | null;
  created_at: string;
}

const API_BASE_URL = 'http://localhost:8000';

// ============================================
// Main Component
// ============================================

export default function AdminUserHistoryPage() {
  const router = useRouter();
  const { user, isLoggedIn } = useAuth();

  const [users, setUsers] = useState<User[]>([]);
  const [selectedUserId, setSelectedUserId] = useState<number | null>(null);
  const [selectedActionType, setSelectedActionType] = useState<ActionType>('all');
  const [histories, setHistories] = useState<UserHistory[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const [currentPage, setCurrentPage] = useState(1);
  const [totalItems, setTotalItems] = useState(0);
  const itemsPerPage = 20;

  // Admin 권한 체크
  useEffect(() => {
    if (isLoggedIn === false) {
      router.push('/auth/login');
      return;
    }

    // TODO: admin 권한 체크 로직 추가
    // if (user && user.role !== 'admin') {
    //   router.push('/');
    //   return;
    // }
  }, [isLoggedIn, user, router]);

  // 사용자 목록 로드
  useEffect(() => {
    if (isLoggedIn) {
      loadUsers();
    }
  }, [isLoggedIn]);

  // 히스토리 로드
  useEffect(() => {
    if (selectedUserId) {
      loadHistories();
    } else {
      setHistories([]);
      setTotalItems(0);
    }
  }, [selectedUserId, selectedActionType, currentPage]);

  const loadUsers = async () => {
    try {
      const response = await fetch(`${API_BASE_URL}/users/`, {
        credentials: 'include',
      });

      if (!response.ok) {
        throw new Error('사용자 목록을 불러올 수 없습니다');
      }

      const data = await response.json();
      setUsers(data);
    } catch (err) {
      console.error('Failed to load users:', err);
      setError(err instanceof Error ? err.message : '사용자 목록 로드 실패');
    }
  };

  const loadHistories = async () => {
    if (!selectedUserId) return;

    setLoading(true);
    setError('');

    try {
      const skip = (currentPage - 1) * itemsPerPage;
      const params = new URLSearchParams({
        skip: skip.toString(),
        limit: itemsPerPage.toString(),
      });

      if (selectedActionType !== 'all') {
        params.append('action_type', selectedActionType);
      }

      const response = await fetch(
        `${API_BASE_URL}/user-history/users/${selectedUserId}/history?${params.toString()}`,
        {
          credentials: 'include',
        }
      );

      if (!response.ok) {
        throw new Error('히스토리를 불러올 수 없습니다');
      }

      const data = await response.json();
      setHistories(data);
      // Note: 실제 총 개수는 API에서 제공해야 하지만, 현재는 데이터 길이로 추정
      setTotalItems(data.length === itemsPerPage ? (currentPage + 1) * itemsPerPage : skip + data.length);
    } catch (err) {
      console.error('Failed to load histories:', err);
      setError(err instanceof Error ? err.message : '히스토리 로드 실패');
    } finally {
      setLoading(false);
    }
  };

  const handleUserSelect = (userId: number) => {
    setSelectedUserId(userId);
    setCurrentPage(1);
  };

  const handleActionTypeChange = (actionType: ActionType) => {
    setSelectedActionType(actionType);
    setCurrentPage(1);
  };

  const formatDate = (dateString: string) => {
    return new Date(dateString).toLocaleString('ko-KR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  const getActionTypeLabel = (actionType: string) => {
    const labels: Record<string, string> = {
      login: '로그인',
      logout: '로그아웃',
      cart_add: '장바구니 추가',
      cart_remove: '장바구니 삭제',
      order_create: '결제 완료',
      order_cancel: '주문 취소',
      refund_request: '환불 요청',
      review_create: '리뷰 작성',
    };
    return labels[actionType] || actionType;
  };

  const selectedUser = users.find(u => u.id === selectedUserId);

  const totalPages = Math.ceil(totalItems / itemsPerPage);

  return (
    <div className={styles.container}>
      <div className={styles.header}>
        <h1 className={styles.title}>사용자 행동 히스토리 관리</h1>
        <p className={styles.subtitle}>Admin Dashboard</p>
      </div>

      {error && (
        <div className={styles.errorBanner}>
          {error}
        </div>
      )}

      <div className={styles.content}>
        {/* 사용자 선택 섹션 */}
        <div className={styles.section}>
          <h2 className={styles.sectionTitle}>1. 사용자 선택</h2>
          <div className={styles.userGrid}>
            {users.map(user => (
              <button
                key={user.id}
                className={`${styles.userCard} ${selectedUserId === user.id ? styles.userCardActive : ''}`}
                onClick={() => handleUserSelect(user.id)}
              >
                <div className={styles.userInfo}>
                  <div className={styles.userId}>ID: {user.id}</div>
                  <div className={styles.userName}>{user.name}</div>
                  <div className={styles.userEmail}>{user.email}</div>
                  <div className={styles.userDate}>
                    가입: {new Date(user.created_at).toLocaleDateString('ko-KR')}
                  </div>
                </div>
              </button>
            ))}
          </div>
        </div>

        {/* 필터 섹션 */}
        {selectedUserId && (
          <div className={styles.section}>
            <h2 className={styles.sectionTitle}>
              2. 액션 타입 필터
              {selectedUser && (
                <span className={styles.selectedUserBadge}>
                  선택된 사용자: {selectedUser.name} ({selectedUser.email})
                </span>
              )}
            </h2>
            <div className={styles.filterButtons}>
              {(['all', 'login', 'logout', 'cart_add', 'cart_remove', 'order_create', 'order_cancel', 'refund_request', 'review_create'] as ActionType[]).map(actionType => (
                <button
                  key={actionType}
                  className={`${styles.filterButton} ${selectedActionType === actionType ? styles.filterButtonActive : ''}`}
                  onClick={() => handleActionTypeChange(actionType)}
                >
                  {actionType === 'all' ? '전체' : getActionTypeLabel(actionType)}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* 히스토리 테이블 */}
        {selectedUserId && (
          <div className={styles.section}>
            <h2 className={styles.sectionTitle}>
              3. 히스토리 목록
              <span className={styles.totalCount}>
                총 {totalItems}개
              </span>
            </h2>

            {loading ? (
              <div className={styles.loading}>데이터를 불러오는 중...</div>
            ) : histories.length === 0 ? (
              <div className={styles.empty}>히스토리가 없습니다.</div>
            ) : (
              <>
                <div className={styles.tableWrapper}>
                  <table className={styles.table}>
                    <thead>
                      <tr>
                        <th>ID</th>
                        <th>액션 타입</th>
                        <th>상품 정보</th>
                        <th>주문/장바구니 ID</th>
                        <th>검색 키워드</th>
                        <th>메타데이터</th>
                        <th>발생 시각</th>
                      </tr>
                    </thead>
                    <tbody>
                      {histories.map(history => (
                        <tr key={history.id}>
                          <td>{history.id}</td>
                          <td>
                            <span className={styles.actionBadge}>
                              {getActionTypeLabel(history.action_type)}
                            </span>
                          </td>
                          <td>
                            {history.product_option_type && history.product_option_id ? (
                              <div className={styles.productInfo}>
                                <div>{history.product_option_type}</div>
                                <div className={styles.productId}>ID: {history.product_option_id}</div>
                              </div>
                            ) : (
                              <span className={styles.noData}>-</span>
                            )}
                          </td>
                          <td>
                            {history.order_id ? (
                              <div className={styles.idInfo}>주문: {history.order_id}</div>
                            ) : history.cart_item_id ? (
                              <div className={styles.idInfo}>장바구니: {history.cart_item_id}</div>
                            ) : (
                              <span className={styles.noData}>-</span>
                            )}
                          </td>
                          <td>
                            {history.search_keyword ? (
                              <span className={styles.keyword}>{history.search_keyword}</span>
                            ) : (
                              <span className={styles.noData}>-</span>
                            )}
                          </td>
                          <td>
                            {history.action_metadata ? (
                              <details className={styles.metadata}>
                                <summary>보기</summary>
                                <pre>{JSON.stringify(JSON.parse(history.action_metadata), null, 2)}</pre>
                              </details>
                            ) : (
                              <span className={styles.noData}>-</span>
                            )}
                          </td>
                          <td className={styles.dateCell}>
                            {formatDate(history.created_at)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>

                {/* 페이지네이션 */}
                {totalPages > 1 && (
                  <div className={styles.pagination}>
                    <button
                      className={styles.pageButton}
                      onClick={() => setCurrentPage(prev => Math.max(1, prev - 1))}
                      disabled={currentPage === 1}
                    >
                      이전
                    </button>

                    <div className={styles.pageNumbers}>
                      {Array.from({ length: Math.min(5, totalPages) }, (_, i) => {
                        const pageNum = Math.max(1, Math.min(currentPage - 2 + i, totalPages - 4 + i));
                        if (pageNum > totalPages) return null;
                        return (
                          <button
                            key={pageNum}
                            className={`${styles.pageNumber} ${currentPage === pageNum ? styles.pageNumberActive : ''}`}
                            onClick={() => setCurrentPage(pageNum)}
                          >
                            {pageNum}
                          </button>
                        );
                      })}
                    </div>

                    <button
                      className={styles.pageButton}
                      onClick={() => setCurrentPage(prev => Math.min(totalPages, prev + 1))}
                      disabled={currentPage === totalPages}
                    >
                      다음
                    </button>
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
