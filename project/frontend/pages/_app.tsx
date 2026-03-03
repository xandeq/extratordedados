import type { AppProps } from 'next/app'
import Head from 'next/head'
import Layout from '../components/Layout'
import { ToastProvider } from '../components/Toast'
import '../styles/globals.css'

export default function App({ Component, pageProps, router }: AppProps) {
  return (
    <>
      <Head>
        <link rel="icon" type="image/png" sizes="512x512" href="/favicon.png" />
        <link rel="apple-touch-icon" href="/favicon.png" />
        <meta name="theme-color" content="#1e3a8a" />
        <title>Extrator de Dados</title>
      </Head>
      <ToastProvider>
        <Layout>
          <Component {...pageProps} key={router.pathname} />
        </Layout>
      </ToastProvider>
    </>
  )
}
