import React from "react";
import layout from "../../styles/layout.module.css";
import { useAuth } from "../../context/AuthContext";

const MyPage = () => {
  const { user, isAuthenticated, initializing } = useAuth();

  if (initializing) {
    return (
      <div className={layout.section}>
        <p>Loading...</p>
      </div>
    );
  }

  return (
    <div className={layout.section}>
      <div className={layout.card}>
        <h1>마이페이지</h1>
        {isAuthenticated && user ? (
          <>
            <p>이메일: {user.email}</p>
            <p>아이디: {user.username}</p>
            <p>이름: {user.name}</p>
          </>
        ) : (
          <p>로그인 후에 확인할 수 있습니다.</p>
        )}
      </div>
    </div>
  );
};

export default MyPage;
