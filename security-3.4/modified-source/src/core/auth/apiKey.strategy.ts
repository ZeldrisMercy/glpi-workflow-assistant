import { restrictedKeyValid } from '../assistant-restricted';
import { Injectable } from '@nestjs/common';
import { PassportStrategy } from '@nestjs/passport';
import { IApiKeyAuth } from '@waha/core/auth/auth';
import { SessionActions } from '@waha/core/auth/casl.types';
import { HeaderOrQueryApiKeyStrategy } from '@waha/core/auth/HeaderOrQueryApiKeyStrategy';
import { ApiKeyAuthService } from './ApiKeyAuthService';

export interface User {
  isAdmin: boolean;
  session?: string;
  actions?: SessionActions | null;
}

function AdminUser(): User {
  return {
    isAdmin: true,
    session: null,
  };
}

@Injectable()
export class ApiKeyStrategy extends PassportStrategy(
  HeaderOrQueryApiKeyStrategy,
) {
  constructor(
    private auth: IApiKeyAuth,
    private apiKeyService: ApiKeyAuthService,
  ) {
    // @ts-ignore — PassportStrategy mixin doesn't forward constructor arg types
    super(true, (apikey, done) => {
      return this.validate(apikey, done);
    });
  }

  validate(apikey: string, done: (err?, user?: User) => void): void {
    this.user(apikey)
      .then((user) => done(null, user))
      .catch((err) => done(err, null));
  }

  async user(apikey: string): Promise<User> {
    if (process.env.WAHA_ASSISTANT_RESTRICTED === 'true') {
      // Bootstrap middleware limits every HTTP request before native guards.
      // AdminUser is needed for creating default; no admin routes are exposed.
      if (!restrictedKeyValid(apikey)) throw new Error('Invalid restricted credential');
      return AdminUser();
    }
    if (this.auth.isValid(apikey)) {
      return AdminUser();
    }
    return this.apiKeyService.get(apikey);
  }
}
