# Acme Voice AI — Knowledge Base

## Section 1: Overview
Acme Voice AI is an enterprise-grade, ultra-low-latency real-time voice assistant platform. It connects browser microphone input directly to speech recognition, retrieval-augmented generation (RAG), and streaming speech synthesis. It is designed for customer service, appointment scheduling, and technical support with sub-2 second perceived response latency.

## Section 2: Pricing and Plans
Acme Voice AI offers three pricing tiers:
1. **Starter Plan ($49/month)**: Includes up to 1,000 voice minutes per month, standard streaming STT/TTS, up to 10,000 vector documents in Qdrant, and community email support.
2. **Pro Plan ($199/month)**: Includes up to 5,000 voice minutes per month, ultra-fast streaming models, up to 100,000 vector documents, priority email and chat support, and custom webhook integrations.
3. **Enterprise Plan (Custom Pricing)**: Tailored for high-volume deployments. Includes unlimited minutes, dedicated Qdrant and Redis clusters, on-premise or private cloud deployment, sub-second latency SLA (99.99% uptime), and a dedicated technical account manager.

## Section 3: Latency & Performance Targets
- **Time-to-First-Audio (TTFA)**: Targeted at ≤ 1.5 seconds, with a strict maximum SLA of 2.0 seconds.
- **RAG Retrieval Latency**: Targeted at ≤ 150 ms using precomputed Qdrant vector embeddings.
- **LLM Time-to-First-Token (TTFT)**: Targeted at ≤ 800 ms using streaming Gemini models.
- **TTS Synthesis**: Sub-500 ms first audio chunk delivery using Sarvam AI streaming endpoints.

## Section 4: Supported Languages & Accents
The platform natively supports English (Indian, US, UK accents) and 10 Indian languages including Hindi, Bengali, Tamil, Telugu, Kannada, Malayalam, Marathi, Gujarati, Punjabi, and Odia. Automatic code-switching and Hinglish phrases are supported out of the box.

## Section 5: Security, SLAs, & Compliance
- Data is encrypted in transit using TLS 1.3 and at rest using AES-256 encryption.
- We are SOC-2 Type II certified and GDPR compliant.
- No client voice audio is stored permanently unless explicit logging is enabled by the customer.
- Availability SLA is 99.9% for Pro tier and 99.99% for Enterprise tier.

## Section 6: Cancellation and Refund Policy
Subscriptions can be cancelled at any time from the account settings dashboard. We offer a full 14-day money-back guarantee for Starter and Pro plans if you are not satisfied with the latency or service quality. Enterprise contracts follow the terms agreed in the custom Master Services Agreement.
