'use client';

import { useAuth } from './authcontext';
import { ChatbotFab } from '@skn/shared-chatbot';

export default function ChatbotFabWrapper() {
  const { isLoggedIn } = useAuth();
  
  return <ChatbotFab isLoggedIn={isLoggedIn} />;
}
