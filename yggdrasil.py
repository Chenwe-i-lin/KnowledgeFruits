from base import config, cache, app, Token
from flask import request, Response
import json
import uuid
import model
import utils
from urllib.parse import parse_qs, urlencode, urlparse
import password
import time
import datetime
import Exceptions

@app.route("/api/knowledgefruits/serverinfo/yggdrasil")
@app.route(config.const.base + '/', methods=['GET'])
def index():
    return Response(json.dumps({
        "meta" : config.YggdrasilIndexData,
        "skinDomains": config.SiteDomain if "SiteDomain" in config.__dict__ else [urlparse(request.url).netloc.split(":")[0]],
        "signaturePublickey": open(config.KeyPath.Public, 'r').read()
    }), mimetype='application/json; charset=utf-8')

# /authserver
@app.route(config.const.base + '/authserver/authenticate', methods=['POST'])
def authenticate():
    IReturn = {}
    if request.is_json:
        data = request.json
        user = model.getuser(data['username'])
        if not user:
            raise Exceptions.InvalidCredentials()
        '''if user.permission == 0:
            return Response(json.dumps({
                'error' : "ForbiddenOperationException",
                'errorMessage' : "You have been banned by the administrator, please contact the administrator for help"
            }), status=403, mimetype='application/json; charset=utf-8')'''
        if not cache.get(".".join(['lock', user.email])):
            cache.set(".".join(['lock', user.email]), "LOCKED", ttl=config.AuthLimit)
        else:
            raise Exceptions.InvalidCredentials()

        SelectedProfile = {}
        AvailableProfiles = []
        if password.crypt(data['password'], user.passwordsalt) == user.password:
            # 登录成功.
            ClientToken = data.get("clientToken", str(uuid.uuid4()).replace("-",""))
            AccessToken = str(uuid.uuid4()).replace("-","")
            notDoubleProfile = False

            try:
                AvailableProfiles = [
                    model.format_profile(i, unsigned=True) for i in model.profile.select().where(model.profile.createby==user.uuid)
                ]
            except Exception as e:
                if "profileDoesNotExist" == e.__class__.__name__:
                    pass

            Profileresult = model.getprofile_createby(user.uuid)
            if len(Profileresult) == 1:
                notDoubleProfile = True
                SelectedProfile = model.format_profile(Profileresult.get())

            cache.set(".".join(["token", AccessToken]), {
                "clientToken": ClientToken,
                "bind": Profileresult.get().uuid if notDoubleProfile else None,
                "user": user.uuid,
                "group": "global",
                "createTime": int(time.time())
            }, ttl=config.TokenTime.RefrushTime * config.TokenTime.TimeRange)

            IReturn = {
                "accessToken" : AccessToken,
                "clientToken" : ClientToken,
                "availableProfiles" : AvailableProfiles,
                "selectedProfile" : SelectedProfile
            }
            if "requestUser" in data:
                if data['requestUser']:
                    IReturn['user'] = model.format_user(user)

            if IReturn['selectedProfile'] == {}:
                del IReturn['selectedProfile']
            
            user.last_login = datetime.datetime.now()
            model.log_yggdrasil(
                operational="authserver.authenticate",
                user=user.uuid,
                otherargs=json.dumps({
                    "clientToken": ClientToken
                }),
                IP=request.remote_addr,
                time=datetime.datetime.now()
            ).save()
        else:
            model.log_yggdrasil(
                operational="authserver.authenticate",
                user=user.uuid,
                IP=request.remote_addr,
                time=datetime.datetime.now(),
                successful=False
            ).save()
            raise Exceptions.InvalidCredentials()
        return Response(json.dumps(IReturn), mimetype='application/json; charset=utf-8')

@app.route(config.const.base + '/authserver/refresh', methods=['POST'])
def refresh():
    if request.is_json:
        data = request.json
        Can = False
        AccessToken = data.get('accessToken')
        ClientToken = data.get("clientToken", str(uuid.uuid4()).replace("-", ""))
        IReturn = {}
        if 'clientToken' in data:
            OldToken = Token.gettoken_strict(AccessToken, data.get("clientToken"))
        else:
            OldToken = Token.gettoken_strict(AccessToken)
        if not OldToken:
            model.log_yggdrasil(
                operational="authserver.refrush",
                otherargs=json.dumps({
                    "clientToken": data.get("clientToken")
                }),
                IP=request.remote_addr,
                time=datetime.datetime.now(),
                successful=False
            ).save()
            raise Exceptions.InvalidToken()
        
        if int(time.time()) >= OldToken.get("createTime") + (config.TokenTime.RefrushTime * config.TokenTime.TimeRange):
            model.log_yggdrasil(
                operational="authserver.refrush",
                user=OldToken.get("user"),
                otherargs=json.dumps({
                    "clientToken": data.get("clientToken")
                }),
                IP=request.remote_addr,
                time=datetime.datetime.now(),
                successful=False
            ).save()
            raise Exceptions.InvalidToken()
        User = model.getuser_uuid(OldToken.get("user"))
        TokenSelected = OldToken.get("bind")
        if TokenSelected:
            TokenProfile = model.getprofile_uuid(TokenSelected).get()
        else:
            TokenProfile = {}
        if 'selectedProfile' in data:
            PostProfile = data['selectedProfile']
            needuser = model.getprofile_id_name(PostProfile['id'], PostProfile['name'])
            if not needuser: # 验证客户端提供的角色信息
                raise Exceptions.InvalidToken()
                # 角色不存在.
            else:
                needuser = needuser.get()
                # 验证完毕,有该角色.
                if OldToken.get('bind'): # 如果令牌本来就绑定了角色
                    model.log_yggdrasil(
                        operational="authserver.refrush",
                        user=User.uuid,
                        otherargs=json.dumps({
                            "clientToken": data.get("clientToken")
                        }),
                        IP=request.remote_addr,
                        time=datetime.datetime.now(),
                        successful=False
                    ).save()
                    error = {
                        'error' : 'IllegalArgumentException',
                        'errorMessage' : "Access token already has a profile assigned."
                    }
                    return Response(json.dumps(error), status=400, mimetype='application/json; charset=utf-8')
                if needuser.createby != OldToken.get("user"): # 如果角色不属于用户
                    model.log_yggdrasil(
                        operational="authserver.refrush",
                        user=User.uuid,
                        otherargs=json.dumps({
                            "clientToken": data.get("clientToken")
                        }),
                        IP=request.remote_addr,
                        time=datetime.datetime.now(),
                        successful=False
                    ).save()
                    error = {
                        'error' : "ForbiddenOperationException",
                        'errorMessage' : "Attempting to bind a token to a role that does not belong to its corresponding user."
                    }
                    return Response(json.dumps(error), status=403, mimetype='application/json; charset=utf-8')
                TokenSelected = model.findprofilebyid(PostProfile['id']).uuid
                IReturn['selectedProfile'] = model.format_profile(model.findprofilebyid(PostProfile['id']), unsigned=True)
                Can = True

        NewAccessToken = str(uuid.uuid4()).replace('-', '')
        cache.set(".".join(["token", NewAccessToken]), {
            "clientToken": OldToken.get('clientToken'),
            "bind": TokenSelected,
            "user": OldToken.get("user"),
            "group": "global",
            "createTime": int(time.time())
        }, ttl=config.TokenTime.RefrushTime * config.TokenTime.TimeRange)

        cache.delete(".".join(["token", AccessToken]))
        IReturn['accessToken'] = NewAccessToken
        IReturn['clientToken'] = OldToken.get('clientToken')
        if TokenProfile and not Can:
            IReturn['selectedProfile'] = model.format_profile(TokenProfile, unsigned=True)
        if 'requestUser' in data:
            if data['requestUser']:
                IReturn['user'] = model.format_user(User)

        User.last_login = datetime.datetime.now()
        model.log_yggdrasil(
            operational="authserver.refrush",
            user=User.uuid,
            otherargs=json.dumps({
                "clientToken": data.get("clientToken")
            }),
            IP=request.remote_addr,
            time=datetime.datetime.now()
        ).save()
        
        return Response(json.dumps(IReturn), mimetype='application/json; charset=utf-8')


#查看令牌状态
@app.route(config.const.base + "/authserver/validate", methods=['POST'])
def validate():
    if request.is_json:
        data = request.json
        AccessToken = data['accessToken']
        ClientToken = data.get("clientToken")
        result = Token.gettoken_strict(AccessToken, ClientToken)
        if not result:
            model.log_yggdrasil(
                operational="authserver.validate",
                otherargs=json.dumps({
                    "clientToken": data.get("clientToken")
                }),
                IP=request.remote_addr,
                time=datetime.datetime.now(),
                successful=False
            ).save()
            raise Exceptions.InvalidToken()
        else:
            if Token.is_validate_strict(AccessToken, ClientToken):
                model.log_yggdrasil(
                    user=result.get("user"),
                    operational="authserver.validate",
                    otherargs=json.dumps({
                        "clientToken": data.get("clientToken")
                    }),
                    IP=request.remote_addr,
                    time=datetime.datetime.now(),
                    successful=False
                ).save()
                raise Exceptions.InvalidToken()
            else:
                model.log_yggdrasil(
                    user=result.get("user"),
                    operational="authserver.validate",
                    otherargs=json.dumps({
                        "clientToken": data.get("clientToken")
                    }),
                    IP=request.remote_addr,
                    time=datetime.datetime.now(),
                ).save()
                return Response(status=204)

@app.route(config.const.base + "/authserver/invalidate", methods=['POST'])
def invalidate():
    if request.is_json:
        data = request.json
        AccessToken = data['accessToken']
        ClientToken = data.get("clientToken")

        result = Token.gettoken(AccessToken, ClientToken)
        if result:
            model.log_yggdrasil(
                operational="authserver.invalidate",
                user=result.get("user"),
                otherargs=json.dumps({
                    "clientToken": data.get("clientToken")
                }),
                IP=request.remote_addr,
                time=datetime.datetime.now()
            ).save()
            cache.delete(".".join(['token', AccessToken]))
        else:
            model.log_yggdrasil(
                operational="authserver.invalidate",
                otherargs=json.dumps({
                    "clientToken": data.get("clientToken")
                }),
                IP=request.remote_addr,
                time=datetime.datetime.now(),
                successful=False
            ).save()
            if ClientToken:
                raise Exceptions.InvalidToken()
        #User = model.user.get(email=result.email)
        '''if User.permission == 0:
            return Response(simplejson.dumps({
                'error' : "ForbiddenOperationException",
                'errorMessage' : "You have been banned by the administrator, please contact the administrator for help"
            }), status=403, mimetype='application/json; charset=utf-8')'''
        return Response(status=204)

#@limit
@app.route(config.const.base + '/authserver/signout', methods=['POST'])
def signout():
    if request.is_json:
        data = request.json
        email = data['username']
        passwd = data['password']
        result = model.getuser(email)
        if not result:
            model.log_yggdrasil(
                operational="authserver.signout",
                IP=request.remote_addr,
                time=datetime.datetime.now(),
                successful=False
            ).save()
            raise Exceptions.InvalidCredentials()
        else:
            '''if result.permission == 0:
                return Response(json.dumps({
                    'error' : "ForbiddenOperationException",
                    'errorMessage' : "Invalid credentials. Invalid username or password."
                }), status=403, mimetype='application/json; charset=utf-8')'''
            if not cache.get(".".join(['lock', result.email])):
                cache.set(".".join(['lock', result.email]), "LOCKED", ttl=config.AuthLimit)
            else:
                raise Exceptions.InvalidCredentials()
            if password.crypt(passwd, salt=result.passwordsalt) == result.password:
                Token_result = Token.getalltoken(result)
                if Token_result:
                    for i in Token_result:
                        cache.delete(i)
                model.log_yggdrasil(
                    operational="authserver.signout",
                    user=result.uuid,
                    IP=request.remote_addr,
                    time=datetime.datetime.now()
                ).save()
                return Response(status=204)
            else:
                model.log_yggdrasil(
                    operational="authserver.signout",
                    user=result.uuid,
                    IP=request.remote_addr,
                    time=datetime.datetime.now(),
                    successful=False
                ).save()
                raise Exceptions.InvalidCredentials()

# /authserver

################

# /sessionserver
@app.route(config.const.base + "/sessionserver/session/minecraft/join", methods=['POST'])
def joinserver():
    token = {}
    if request.is_json:
        data = request.json
        AccessToken = data['accessToken']
        ClientToken = data.get("clientToken")
        TokenValidate = Token.is_validate_strict(AccessToken, ClientToken)
        
        if not TokenValidate:
            # Token有效
            # uuid = token.bind
            token = Token.gettoken_strict(AccessToken, ClientToken)
            if not token:
                raise Exceptions.InvalidToken()
            if token.get('bind'):
                result = model.getprofile_uuid(token.get('bind'))
                if not result:
                    return Response(status=404)
            else:
                raise Exceptions.InvalidToken()
            player = model.getprofile(result.get().name).get()
            playeruuid = player.profile_id.replace("-", "")
            if data['selectedProfile'] == playeruuid:
                cache.set(data['serverId'], {
                    "accessToken": AccessToken,
                    "selectedProfile": data['selectedProfile'],
                    "remoteIP": request.remote_addr
                }, ttl=config.ServerIDOutTime)
                model.log_yggdrasil(
                    operational="sessionserver.session.minecraft.join",
                    user=token.get("user"),
                    IP=request.remote_addr,
                    time=datetime.datetime.now()
                ).save()
                return Response(status=204)
            else:
                model.log_yggdrasil(
                    operational="sessionserver.session.minecraft.join",
                    user=token.get("user"),
                    IP=request.remote_addr,
                    time=datetime.datetime.now(),
                    successful=False
                ).save()
                raise Exceptions.InvalidToken()
        else:
            model.log_yggdrasil(
                operational="sessionserver.session.minecraft.join",
                IP=request.remote_addr,
                time=datetime.datetime.now(),
                successful=False
            ).save()
            raise Exceptions.InvalidToken()

@app.route(config.const.base + "/sessionserver/session/minecraft/hasJoined", methods=['GET'])
def PlayerHasJoined():
    args = request.args
    ServerID = args['serverId']
    PlayerName = args['username']
    RemoteIP = args['ip'] if 'ip' in args else None
    Successful = False
    Data = cache.get(ServerID)
    if not Data:
        model.log_yggdrasil(
            operational="sessionserver.session.minecraft.hasJoined",
            IP=request.remote_addr,
            time=datetime.datetime.now(),
            successful=False
        ).save()
        return Response(status=204)
    TokenInfo = Token.gettoken(Data['accessToken'])
    ProfileInfo = model.getprofile_uuid_name(TokenInfo.get("bind"), name=PlayerName)
    if not TokenInfo or not ProfileInfo:
        model.log_yggdrasil(
            operational="sessionserver.session.minecraft.hasJoined",
            IP=request.remote_addr,
            time=datetime.datetime.now(),
            successful=False
        ).save()
        return Response(status=204)

    ProfileInfo = ProfileInfo.get()

    Successful = PlayerName == ProfileInfo.name and [True, RemoteIP == Data['remoteIP']][bool(RemoteIP)]
    if Successful:
        model.log_yggdrasil(
            operational="sessionserver.session.minecraft.hasJoined",
            user=TokenInfo.get("user"),
            IP=request.remote_addr,
            time=datetime.datetime.now()
        ).save()
        result = json.dumps(model.format_profile(
            ProfileInfo,
            Properties=True,
            unsigned=False,
            BetterData=True
        ))
        return Response(result, mimetype="application/json; charset=utf-8")
    else:
        model.log_yggdrasil(
            operational="sessionserver.session.minecraft.hasJoined",
            user=TokenInfo.get("user"),
            IP=request.remote_addr,
            time=datetime.datetime.now(),
            successful=False
        ).save()
        return Response(status=204)
    return Response(status=204)

@app.route(config.const.base + '/sessionserver/session/minecraft/profile/<getuuid>', methods=['GET'])
def searchprofile(getuuid):
    args = request.args
    result = model.getprofile_id(getuuid)
    if not result:
        return Response(status=204)
    else:
        result = result.get()
    IReturn = model.format_profile(
        #model.user.get(model.user.playername == model.profile.get(profile_id=getuuid).name),
        result,
        Properties=True,
        unsigned={"false": False, "true": True, None: True}[args.get('unsigned')],
        BetterData=True
    )
    return Response(response=json.dumps(IReturn), mimetype='application/json; charset=utf-8')

@app.route(config.const.base + '/api/profiles/minecraft', methods=['POST'])
def searchmanyprofile():
    if request.is_json:
        data = list(set(list(request.json)))
        IReturn = []
        for i in range(config.ProfileSearch.MaxAmount - 1):
            try:
                IReturn.append(model.format_profile(model.profile.get(model.profile.name==data[i]), unsigned=True))
            except model.profile.DoesNotExist:
                continue
            except IndexError:
                pass
        return Response(json.dumps(IReturn), mimetype='application/json; charset=utf-8')
    return Response(status=404)
