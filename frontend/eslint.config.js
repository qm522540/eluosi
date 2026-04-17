import js from '@eslint/js'
import react from 'eslint-plugin-react'
import reactHooks from 'eslint-plugin-react-hooks'
import globals from 'globals'

export default [
  { ignores: ['dist/**', 'node_modules/**', 'build/**'] },
  {
    files: ['src/**/*.{js,jsx}'],
    ...js.configs.recommended,
    plugins: { react, 'react-hooks': reactHooks },
    languageOptions: {
      ecmaVersion: 'latest',
      sourceType: 'module',
      parserOptions: { ecmaFeatures: { jsx: true } },
      globals: { ...globals.browser, ...globals.node },
    },
    settings: { react: { version: 'detect' } },
    rules: {
      ...js.configs.recommended.rules,
      ...react.configs.recommended.rules,
      ...reactHooks.configs.recommended.rules,
      // 今早那种 setOptimizedTitle 未定义这类运行时错，pre-commit 必须拦住
      'no-undef': 'error',
      // JSX 里 React 17+ 新 transform 不需要引入 React
      'react/react-in-jsx-scope': 'off',
      'react/prop-types': 'off',
      // 下面几条暂时降为 warn，避免一次性引入大量存量改动
      'no-unused-vars': ['warn', { argsIgnorePattern: '^_', varsIgnorePattern: '^_' }],
      'react/no-unescaped-entities': 'warn',
      'react/display-name': 'warn',
      'react-hooks/exhaustive-deps': 'warn',
    },
  },
]
