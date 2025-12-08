# Mobius Identity Service

Authentication and identity management for the Mobius platform.

## Features

- Email/password signup and login
- JWT token-based authentication
- Secure password hashing (bcrypt)
- Civic ID generation for Civic Protocol integration
- PostgreSQL database support
- CORS enabled for Vercel frontend

## Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/auth/signup` | Create new account |
| `POST` | `/auth/login` | Login with email/password |
| `POST` | `/auth/logout` | Logout (client deletes token) |
| `GET` | `/auth/me` | Get current user |
| `PATCH` | `/auth/me` | Update user profile |
| `GET` | `/auth/introspect` | Introspect token for validation |
| `GET` | `/auth/verify/{civic_id}` | Verify a Civic ID exists |
| `GET` | `/health` | Health check |

## Environment Variables

```bash
DATABASE_URL=postgresql://user:pass@host:5432/dbname  # or sqlite:///./identity.db
SECRET_KEY=your-secret-key-here
PORT=8000
```

## Local Development

```bash
cd identity
pip install -r requirements.txt
python -m app.main
# or
uvicorn app.main:app --reload
```

Open http://localhost:8000/docs for API documentation.

## Testing

```bash
# Signup
curl -X POST http://localhost:8000/auth/signup \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"secret123","name":"Test User"}'

# Login
curl -X POST http://localhost:8000/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"secret123"}'

# Get current user (replace TOKEN)
curl http://localhost:8000/auth/me \
  -H "Authorization: Bearer TOKEN"

# Introspect token
curl http://localhost:8000/auth/introspect \
  -H "Authorization: Bearer TOKEN"
```

## Response Examples

### Signup/Login Response
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user": {
    "id": "550e8400-e29b-41d4-a716-446655440000",
    "email": "test@example.com",
    "name": "Test User",
    "civic_id": "civic::a1b2c3d4e5f6",
    "created_at": "2024-01-15T10:30:00Z"
  }
}
```

### Introspect Response
```json
{
  "active": true,
  "user_id": "550e8400-e29b-41d4-a716-446655440000",
  "civic_id": "civic::a1b2c3d4e5f6",
  "email": "test@example.com",
  "name": "Test User"
}
```

## Deploy to Render

The `render.yaml` in this directory configures deployment:

```bash
# From the identity directory
render deploy
```

Or use the Render dashboard to create a new Web Service pointing to the `identity/` folder.
