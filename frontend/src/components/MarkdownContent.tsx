import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Box, Link, Typography } from '@mui/material'
import type { Components } from 'react-markdown'

interface MarkdownContentProps {
  children: string
}

const components: Components = {
  p: ({ children }) => (
    <Typography variant="body2" component="p" sx={{ mt: 0, mb: 1, '&:last-child': { mb: 0 } }}>
      {children}
    </Typography>
  ),
  strong: ({ children }) => <strong>{children}</strong>,
  em: ({ children }) => <em>{children}</em>,
  h1: ({ children }) => (
    <Typography variant="h6" component="h1" sx={{ mt: 1, mb: 0.5 }}>
      {children}
    </Typography>
  ),
  h2: ({ children }) => (
    <Typography variant="subtitle1" component="h2" fontWeight="bold" sx={{ mt: 1, mb: 0.5 }}>
      {children}
    </Typography>
  ),
  h3: ({ children }) => (
    <Typography variant="body1" component="h3" fontWeight="bold" sx={{ mt: 1, mb: 0.5 }}>
      {children}
    </Typography>
  ),
  code: ({ children, className }) => {
    const isBlock = Boolean(className)
    if (isBlock) {
      return (
        <Box
          component="code"
          sx={{
            display: 'block',
            fontFamily: 'monospace',
            fontSize: '0.85em',
            bgcolor: 'action.hover',
            borderRadius: 1,
            p: 1,
            overflowX: 'auto',
            whiteSpace: 'pre',
          }}
        >
          {children}
        </Box>
      )
    }
    return (
      <Box
        component="code"
        sx={{
          fontFamily: 'monospace',
          fontSize: '0.85em',
          bgcolor: 'action.hover',
          borderRadius: 0.5,
          px: 0.5,
          py: 0.125,
        }}
      >
        {children}
      </Box>
    )
  },
  pre: ({ children }) => (
    <Box
      component="pre"
      sx={{
        mt: 0,
        mb: 1,
        p: 0,
        bgcolor: 'transparent',
        overflow: 'auto',
        '&:last-child': { mb: 0 },
      }}
    >
      {children}
    </Box>
  ),
  a: ({ href, children }) => (
    <Link
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      sx={{ color: 'primary.main' }}
    >
      {children}
    </Link>
  ),
  ul: ({ children }) => (
    <Box
      component="ul"
      sx={{
        mt: 0,
        mb: 1,
        pl: 3,
        '& li': { typography: 'body2', mb: 0.25 },
        '&:last-child': { mb: 0 },
      }}
    >
      {children}
    </Box>
  ),
  ol: ({ children }) => (
    <Box
      component="ol"
      sx={{
        mt: 0,
        mb: 1,
        pl: 3,
        '& li': { typography: 'body2', mb: 0.25 },
        '&:last-child': { mb: 0 },
      }}
    >
      {children}
    </Box>
  ),
  li: ({ children }) => <li>{children}</li>,
  blockquote: ({ children }) => (
    <Box
      component="blockquote"
      sx={{
        mt: 0,
        mb: 1,
        pl: 1.5,
        borderLeft: '3px solid',
        borderColor: 'divider',
        color: 'text.secondary',
        '& p': { mb: 0 },
        '&:last-child': { mb: 0 },
      }}
    >
      {children}
    </Box>
  ),
}

export default function MarkdownContent({ children }: MarkdownContentProps) {
  return (
    <Box sx={{ typography: 'body2' }}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </Box>
  )
}
