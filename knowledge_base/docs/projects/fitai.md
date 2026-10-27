---
project_id: fitai
status: shipped
---

# FitAI — AI Fitness Platform

## Overview

FitAI is a full-stack fitness platform for workout planning and logging, progress analytics, profile management, and AI-assisted fitness insights. It integrates Google Gemini to analyze workout performance, suggest workout-plan adjustments, and power an AI coach whose conversation history is persisted.

The project is designed as a React frontend and Node.js REST API backed by MongoDB, with Docker Compose for local service setup.

## Architecture

FitAI is organized as a frontend application and backend API:

- **Frontend:** React 19, React Router 7, Vite 7, Tailwind CSS 4, Axios, Framer Motion, and Recharts.
- **Backend:** Node.js with ES modules, Express 5, Mongoose 9, and Joi request validation.
- **Database:** MongoDB 7, with Mongoose models.
- **AI:** Google Gemini API through `@google/genai`.
- **Email:** Resend for OTP delivery.
- **Security and operations:** JWT authentication, password hashing with `bcryptjs`, Helmet, CORS, XSS-related middleware, NoSQL-injection sanitization, HPP protection, rate limiting, Winston, and Morgan.
- **Container setup:** Docker Compose.

### Request flow

1. The React frontend sends HTTP requests to the Express API.
2. Route middleware handles relevant authentication, authorization, validation, and rate limiting.
3. Controllers delegate application work to service-layer functions.
4. Services use Mongoose models to read and update MongoDB documents.
5. AI-related services can call Gemini; OTP email flows use Resend.
6. The API returns structured JSON responses to the frontend.

### Backend module structure

The backend separates routes, controllers, services, models, middleware, configuration, and Joi validation. This separates HTTP concerns from application logic and database access.

## Main Features

### Fitness planning and logging

- Create, fetch, update, and delete a workout plan.
- Record workout logs and retrieve historical logs with pagination/date-range support.
- Track progress through streaks, summaries, monthly views, insights, and exercise analytics.
- Browse and filter the exercise library.
- Manage user profile, theme, avatar, and nutrition preferences.

### AI-assisted fitness features

- **Performance analysis:** the `/ai/analyze` endpoint uses Gemini for AI-assisted performance insights.
- **Workout-plan adjustments:** `/ai/adjust-plan` provides suggested changes to a workout plan.
- **AI coach:** `/ai/chat` supports retrieving chat history, sending messages, and clearing history.
- **Structured context:** `/ai/context` provides context used by AI features.

AI output is advisory application output, not a substitute for qualified medical or fitness advice.

### Authentication and user roles

- Registration and OTP verification.
- OTP resend and login/logout flows.
- JWT-based authentication with bearer-token and cookie support.
- Role checks for protected administrative functionality.
- Password hashing using `bcryptjs`.

## Data Model

The documented model relationships and responsibilities are:

- **User:** authentication, role, verification state, profile, fitness goal/level, theme, nutrition preferences, and OTP-related fields. Email is unique; the password field is hidden from normal query results.
- **WorkoutPlan:** one plan per user, with a plan name and workouts grouped by day. Plan exercises reference exercise records and can include sets, reps, and weight.
- **WorkoutLog:** a user's executed workout history, including date, status, performed exercises, and notes.
- **Exercise:** canonical exercise library entries, including name, muscle group, secondary muscles, equipment, category, difficulty, and image.
- **ChatSession:** persisted AI-coach messages for a user; `userId` is unique. Messages record role and content.
- **Testimonial:** user review text, rating, author information, and approval state.

The schema also models plan exercises and performed exercises as embedded collections with references to exercise records, as documented in the project README.

## Security, Validation, and Reliability

- JWT authentication accepts bearer tokens and supports cookie-based authentication.
- Role-based access protects admin functionality.
- Joi schemas validate requests in route modules.
- Rate limiting includes a global limiter and stricter limiters for authentication and selected AI endpoints.
- Helmet, CORS configuration, XSS-related middleware, NoSQL sanitization, and HPP middleware form the documented security middleware stack.
- Centralized error handling converts errors into structured API responses.
- Winston and Morgan provide application and HTTP logging.
- `JWT_SECRET` must be at least 32 characters according to startup validation.
- Production configuration requires the frontend origin and Resend key; Gemini API access requires `GEMINI_API_KEY`.

These controls do not imply that the application is immune to security issues; claims should be limited to the protections present in the code and active configuration.

## Scope and Limitations

- **Scope:** FitAI is built for strength-training workflows: one workout plan per user, with sets logged as weight × reps. Cardio, duration-based and bodyweight-specific tracking are not supported.
- **Logging rules:** Workouts can only be logged for today or yesterday, and only on the planned day. Day boundaries are calculated in UTC, so streaks and dates can be off for users in other timezones.
- **AI features are advisory:** Analysis, plan adjustments and chat use Gemini 2.5 Flash on a recent data window (about 30 days). Suggestions are never applied automatically, and output quality is not yet measured by a formal evaluation suite.
- **Auth:** Sessions use a 30-minute JWT with no refresh token and no password-reset flow. OTP attempts are rate-limited per IP, not per account.
- **Engineering:** There are no automated tests yet. Rate limits and the AI analysis cache are in-memory or per-user in the database, which limits horizontal scaling, and the stored nutrition profile is not yet used by analytics or AI prompts.

## Future Work

- **AI evaluation and grounding:** Add an evaluation harness (schema validity, plan-change constraints, no invented metrics), use Gemini structured outputs, and replace the regex intent router with tool calling over the user's own data.
- **Knowledge-grounded coaching:** Add retrieval over an evidence-based fitness knowledge base with citations and injury/medical safety guardrails.
- **Deterministic progression engine:** Build rule-based progressive overload and deload recommendations, with the LLM used only to explain them.
- **Product depth:** Add per-user timezones, log editing and backfill, multiple plans and templates, RPE/RIR tracking, cardio exercises and nutrition tracking.
- **Reliability and security:** Add unit, integration and end-to-end tests with a real CI gate, Redis-backed rate limiting and caching, refresh tokens with password reset, and prompt/latency/cost observability.


## Project Links

- Repository: https://github.com/Arjun8242/FitAI
- Live application: https://performance-tracker-zeta.vercel.app/
