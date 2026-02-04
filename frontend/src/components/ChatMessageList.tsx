import React from 'react';
import { Avatar } from 'antd';
import { RobotOutlined, UserOutlined } from '@ant-design/icons';

export type ChatMessage = {
  role: 'user' | 'ai';
  content: string;
  timestamp: string;
};

type Variant = 'agent' | 'customer' | 'global';

type ChatMessageListProps = {
  messages: ChatMessage[];
  variant: Variant;
  className?: string;
  containerRef?: React.RefObject<HTMLDivElement>;
  emptyState?: React.ReactNode;
};

const renderAgentMessage = (msg: ChatMessage, idx: number) => (
  <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
    <div
      className={`max-w-[80%] rounded-2xl p-4 shadow-sm ${
        msg.role === 'user'
          ? 'bg-purple-600 text-white rounded-br-none'
          : 'bg-white border border-gray-100 text-gray-800 rounded-bl-none'
      }`}
    >
      <div className="whitespace-pre-wrap">{msg.content}</div>
      <div className={`text-xs mt-1.5 ${msg.role === 'user' ? 'text-purple-200' : 'text-gray-400'}`}>
        {new Date(msg.timestamp).toLocaleTimeString()}
      </div>
    </div>
  </div>
);

const renderCustomerMessage = (msg: ChatMessage, idx: number) => (
  <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
    <div className={`flex gap-3 max-w-[80%] ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
      <Avatar
        icon={msg.role === 'user' ? <UserOutlined /> : <RobotOutlined />}
        className={msg.role === 'user' ? 'bg-blue-500' : 'bg-green-500'}
      />
      <div
        className={`p-3 rounded-xl shadow-sm whitespace-pre-wrap ${
          msg.role === 'user'
            ? 'bg-blue-500 text-white rounded-tr-none'
            : 'bg-white border text-gray-700 rounded-tl-none'
        }`}
      >
        {msg.content}
      </div>
    </div>
  </div>
);

const renderGlobalMessage = (msg: ChatMessage, idx: number) => (
  <div key={idx} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'} animate-fade-in`}>
    <div className={`flex gap-2 max-w-[90%] ${msg.role === 'user' ? 'flex-row-reverse' : 'flex-row'}`}>
      <Avatar
        size="small"
        src={msg.role === 'ai' ? 'https://api.dicebear.com/7.x/bottts/svg?seed=ai' : undefined}
        icon={msg.role === 'user' ? <UserOutlined /> : undefined}
        className={msg.role === 'user' ? 'bg-blue-600 mt-0.5' : 'bg-transparent mt-0.5'}
      />
      <div>
        <div
          className={`px-3 py-2 rounded-xl text-sm whitespace-pre-wrap leading-relaxed ${
            msg.role === 'user'
              ? 'bg-blue-600 text-white rounded-tr-none'
              : 'bg-white border border-gray-100 text-gray-700 rounded-tl-none shadow-sm'
          }`}
        >
          {msg.content}
        </div>
      </div>
    </div>
  </div>
);

const ChatMessageList: React.FC<ChatMessageListProps> = ({
  messages,
  variant,
  className,
  containerRef,
  emptyState,
}) => {
  const renderMessage = (msg: ChatMessage, idx: number) => {
    if (variant === 'agent') return renderAgentMessage(msg, idx);
    if (variant === 'customer') return renderCustomerMessage(msg, idx);
    return renderGlobalMessage(msg, idx);
  };

  return (
    <div className={className} ref={containerRef}>
      {messages.length === 0 ? emptyState : messages.map(renderMessage)}
    </div>
  );
};

export default ChatMessageList;
