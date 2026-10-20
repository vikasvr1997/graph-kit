import { initializeApp } from 'firebase/app'
import {
  type User, GoogleAuthProvider, getAuth, onAuthStateChanged, signInWithCustomToken,
  signInWithPopup, signOut,
} from 'firebase/auth'

const app = initializeApp({
  apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
  authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
  projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
  storageBucket: import.meta.env.VITE_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: import.meta.env.VITE_FIREBASE_MESSAGING_SENDER_ID,
  appId: import.meta.env.VITE_FIREBASE_APP_ID,
})

export const auth = getAuth(app)

export function signInWithGoogle() {
  return signInWithPopup(auth, new GoogleAuthProvider())
}

export function signOutUser() {
  return signOut(auth)
}

export function onAuthChange(cb: (user: User | null) => void) {
  return onAuthStateChanged(auth, cb)
}

export async function currentIdToken(): Promise<string | null> {
  const user = auth.currentUser
  return user ? user.getIdToken() : null
}

// Dev-only test hook: lets Playwright sign in with a custom token (minted via a
// dedicated service account) instead of driving the real Google OAuth popup.
// Stripped from production builds since it's gated on import.meta.env.DEV.
if (import.meta.env.DEV) {
  ;(window as unknown as { __graphkitTestSignIn?: (token: string) => Promise<string> }).__graphkitTestSignIn =
    async (token: string) => (await signInWithCustomToken(auth, token)).user.uid
}
