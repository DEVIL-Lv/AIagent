import React, { useMemo, useState } from 'react';
import { Avatar, Collapse, Tag, Typography } from 'antd';
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

type StructuredInfoRecord = {
  updatedAt?: string;
  fields: Record<string, string>;
};

type StructuredInfoTable = {
  name: string;
  records: StructuredInfoRecord[];
};

type StructuredInfo = {
  basic: Record<string, string>;
  tables: StructuredInfoTable[];
  archives: string[];
};

const parseTimestamp = (ts: string) => {
  const hasTz = /Z$|[+-]\d{2}:\d{2}$/.test(ts);
  const pure = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?$/.test(ts);
  const target = !hasTz && pure ? `${ts}Z` : ts;
  return new Date(target);
};

const isStructuredInfoContent = (content: string) => {
  if (!content) return false;
  return (
    content.includes('【客户基本信息】') ||
    content.includes('【档案资料】') ||
    /【.+?】/.test(content)
  );
};

const normalizeCellValue = (value: string) =>
  value.replace(/\\\|/g, '|').replace(/<br\s*\/?>/gi, '\n').trim();

const splitPipeRow = (line: string) => line.split(' | ').map((v) => normalizeCellValue(v));

const parseKeyValueLine = (line: string): [string, string] | null => {
  const sep = line.includes('：') ? '：' : line.includes(':') ? ':' : null;
  if (!sep) return null;
  const idx = line.indexOf(sep);
  if (idx <= 0) return null;
  const key = line.slice(0, idx).trim();
  const value = line.slice(idx + 1).trim();
  if (!key) return null;
  return [key, value];
};

const parseStructuredInfo = (content: string): StructuredInfo | null => {
  if (!isStructuredInfoContent(content)) return null;

  const lines = content.replace(/\r\n/g, '\n').split('\n');
  const basic: Record<string, string> = {};
  const tables: StructuredInfoTable[] = [];
  const archives: string[] = [];

  const isDelimiter = (s: string) => s.trim() === '----------------';
  const isSectionHeader = (s: string) => s.startsWith('【') && s.endsWith('】') && s !== '【数据详情】';

  const parseUpdatedAt = (line: string) => {
    const kv = parseKeyValueLine(line);
    if (!kv) return null;
    const [k, v] = kv;
    if (!k.includes('更新时间')) return null;
    return normalizeCellValue(v);
  };

  const tryExtractUpdatedAtFromRow = (row: Record<string, string>) => {
    const keys = Object.keys(row);
    const direct = keys.find((k) => k.includes('更新时间')) || keys.find((k) => k.includes('创建时间'));
    return direct ? normalizeCellValue(String(row[direct] ?? '')) : undefined;
  };

  let i = 0;
  while (i < lines.length) {
    const raw = lines[i];
    const line = (raw || '').trim();
    if (!line) {
      i += 1;
      continue;
    }

    if (line === '【客户基本信息】') {
      i += 1;
      while (i < lines.length) {
        const l = (lines[i] || '').trim();
        if (!l) {
          i += 1;
          continue;
        }
        if (isDelimiter(l) || isSectionHeader(l)) break;
        const kv = parseKeyValueLine(l);
        if (kv) basic[kv[0]] = kv[1];
        i += 1;
      }
      continue;
    }

    if (isSectionHeader(line) && line !== '【客户基本信息】' && line !== '【档案资料】') {
      const name = line.slice(1, -1).trim() || '表格';
      const cleanName = name.startsWith('表格：') ? name.slice('表格：'.length).trim() : name;
      
      i += 1;
      while (i < lines.length && !(lines[i] || '').trim()) i += 1;
      const firstLine = ((lines[i] || '') as string).trim();

      const records: StructuredInfoRecord[] = [];
      if (firstLine === '【数据详情】' || firstLine.startsWith('更新时间')) {
        while (i < lines.length) {
          const l = (lines[i] || '').trim();
          if (!l) {
            i += 1;
            continue;
          }
          if (isDelimiter(l)) {
            i += 1;
            continue;
          }
          if (isSectionHeader(l)) break;

          let updatedAt: string | undefined;
          const fields: Record<string, string> = {};

          if (l === '【数据详情】') {
            i += 1;
          }

          while (i < lines.length) {
            const lineIn = (lines[i] || '').trim();
            if (!lineIn) {
              i += 1;
              continue;
            }
            if (isDelimiter(lineIn) || isSectionHeader(lineIn) || lineIn === '【数据详情】') break;
            
            const kv = parseKeyValueLine(lineIn);
            if (kv) {
                if (kv[0].includes('更新时间')) {
                    updatedAt = kv[1];
                } else {
                    fields[kv[0]] = kv[1];
                }
            }
            i += 1;
          }
          records.push({ updatedAt, fields });
        }
        tables.push({ name: cleanName, records });
      }
      continue;
    }
    
    if (line === '【档案资料】') {
       i += 1;
       while (i < lines.length) {
         const l = (lines[i] || '').trim();
         if (!l) {
            i += 1;
            continue;
         }
         if (isSectionHeader(l)) break;
         if (l.startsWith('- ')) {
             archives.push(l.slice(2).trim());
         } else {
             archives.push(l);
         }
         i += 1;
       }
       continue;
    }

    i += 1;
  }

  return { basic, tables, archives };
};

const getStageLabel = (stage: string) => {
  switch (stage) {
    case 'closing':
      return '商务谈判';
    case 'product_matching':
      return '需求分析';
    case 'trust_building':
      return '建立信任';
    case 'contact_before':
      return '待开发';
    default:
      return stage;
  }
};

const renderValue = (key: string, value: string) => {
  if (key.includes('阶段') && value) return <Tag color="gold">{getStageLabel(value)}</Tag>;
  if (key.includes('风险') && value) return <Tag color="geekblue">{value}</Tag>;
  return <span className="text-xs text-gray-700 whitespace-pre-wrap break-words">{value}</span>;
};

const ValueCell: React.FC<{ value: string }> = ({ value }) => {
  const v = String(value ?? '');
  const shouldEllipsis = v.length > 120 || v.includes('\n');
  if (!shouldEllipsis) return <span className="text-xs text-gray-700 whitespace-pre-wrap break-words">{v}</span>;
  return (
    <Typography.Paragraph className="mb-0 text-xs text-gray-700 whitespace-pre-wrap" ellipsis={{ rows: 3, expandable: true, symbol: '展开' }}>
      {v}
    </Typography.Paragraph>
  );
};

const KeyValueGrid: React.FC<{ entries: [string, React.ReactNode][] }> = ({ entries }) => (
  <div className="grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-3">
    {entries.map(([k, v]) => (
      <div key={k} className="flex gap-3 min-w-0">
        <div className="w-24 text-[11px] text-gray-400 shrink-0 truncate" title={k}>
          {k}
        </div>
        <div className="flex-1 min-w-0">{v}</div>
      </div>
    ))}
  </div>
);

const StructuredRecordCard: React.FC<{ record: StructuredInfoRecord }> = ({ record }) => {
  const [expanded, setExpanded] = useState(false);
  const allFields = Object.entries(record.fields || {});
  const showFields = expanded ? allFields : allFields.slice(0, 10);
  const hasMore = allFields.length > showFields.length;

  return (
    <div className="bg-white border border-gray-100 rounded-xl shadow-sm px-4 py-3">
      {record.updatedAt && (
        <div className="flex items-center justify-end gap-3 mb-2">
          <div className="text-[11px] text-gray-400 shrink-0">更新时间：{record.updatedAt}</div>
        </div>
      )}
      {showFields.length > 0 ? (
        <KeyValueGrid
          entries={showFields.map(([k, v]) => [k, <ValueCell key={k} value={normalizeCellValue(String(v ?? ''))} />])}
        />
      ) : (
        <div className="text-xs text-gray-400">暂无数据</div>
      )}
      {hasMore && (
        <div className="pt-2">
          <button
            type="button"
            className="text-xs text-blue-600 hover:text-blue-700"
            onClick={() => setExpanded((s) => !s)}
          >
            {expanded ? '收起' : `展开更多（${allFields.length - showFields.length}）`}
          </button>
        </div>
      )}
    </div>
  );
};

const StructuredInfoMessage: React.FC<{ content: string }> = ({ content }) => {
  const parsed = useMemo(() => parseStructuredInfo(content), [content]);
  if (!parsed) return <div className="whitespace-pre-wrap">{content}</div>;

  const basicItems = Object.entries(parsed.basic);
  const hasBasic = basicItems.length > 0;
  const hasTables = parsed.tables.length > 0;
  const hasArchives = parsed.archives.length > 0;

  const basicRows = (
    <div className="bg-white border border-gray-100 rounded-xl shadow-sm px-4 py-3">
      <div className="font-medium text-gray-800 text-sm mb-2">客户基本信息</div>
      <KeyValueGrid entries={basicItems.map(([k, v]) => [k, renderValue(k, normalizeCellValue(v))])} />
    </div>
  );

  const collapseItems = [
    ...(hasTables
      ? parsed.tables.map((t) => ({
          key: `table:${t.name}`,
          label: (
            <div className="flex items-center gap-2">
              <span className="font-medium">{t.name}</span>
              <Tag color="blue">{t.records.length} 条</Tag>
            </div>
          ),
          children: (
            <div className="space-y-3">
              {t.records.length > 0 ? (
                t.records.map((r, idx) => <StructuredRecordCard key={`${t.name}-${idx}`} record={r} />)
              ) : (
                <div className="text-xs text-gray-400">暂无数据</div>
              )}
            </div>
          ),
        }))
      : []),
    ...(hasArchives
      ? [
          {
            key: 'archives',
            label: (
              <div className="flex items-center gap-2">
                <span className="font-medium">档案资料</span>
                <Tag>{parsed.archives.length}</Tag>
              </div>
            ),
            children: (
              <div className="space-y-1">
                {parsed.archives.map((a, idx) => (
                  <Typography.Paragraph
                    key={`${idx}-${a.slice(0, 12)}`}
                    className="mb-1 text-xs text-gray-700 whitespace-pre-wrap"
                    ellipsis={{ rows: 2, expandable: true, symbol: '展开' }}
                  >
                    {a}
                  </Typography.Paragraph>
                ))}
              </div>
            ),
          },
        ]
      : []),
  ];

  return (
    <div className="space-y-2">
      {hasBasic && basicRows}
      {(hasTables || hasArchives) && <Collapse size="small" items={collapseItems} />}
      {!hasTables && !hasArchives && !hasBasic && (
        <div className="whitespace-pre-wrap text-xs text-gray-600">{content}</div>
      )}
    </div>
  );
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
      {msg.role === 'ai' ? <StructuredInfoMessage content={msg.content} /> : <div className="whitespace-pre-wrap">{msg.content}</div>}
      <div className={`text-xs mt-1.5 ${msg.role === 'user' ? 'text-purple-200' : 'text-gray-400'}`}>
        {parseTimestamp(msg.timestamp).toLocaleString('zh-CN', {
          year: 'numeric',
          month: '2-digit',
          day: '2-digit',
          hour: '2-digit',
          minute: '2-digit',
          second: '2-digit',
          hour12: false,
        })}
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
        {msg.role === 'ai' ? <StructuredInfoMessage content={msg.content} /> : msg.content}
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
          {msg.role === 'ai' ? <StructuredInfoMessage content={msg.content} /> : msg.content}
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
